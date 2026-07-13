/**
 * SmbFolderPicker — sélection d'UN dossier de périmètre (partages → arborescence)
 * ==============================================================================
 * Réutilise l'exploration des sources (mêmes API `shares` / `browse` que
 * « Sources de fichiers »), mais en **choix unique** : l'utilisateur navigue puis
 * clique « Choisir ce dossier ». Renvoie le préfixe de chemin (`smb://hôte/partage/…`)
 * et un libellé lisible, sans indexer ni déplacer quoi que ce soit.
 */
import { useEffect, useState } from 'react'
import { Folder, FolderOpen, Server, ChevronRight, X, RefreshCw, Check } from 'lucide-react'
import { sourcesApi, type Source, type BrowseEntry } from '../../api'
import { useToast } from '../common/Toast'

export default function SmbFolderPicker({ source, onPick, onClose }: {
  source: Source
  onPick: (prefixe: string, label: string) => void
  onClose: () => void
}) {
  const toast = useToast()
  const [shares, setShares] = useState<string[]>([])
  const [partage, setPartage] = useState<string | null>(null)
  const [chemin, setChemin] = useState('/')
  const [entries, setEntries] = useState<BrowseEntry[]>([])
  const [loading, setLoading] = useState(false)

  const joinPath = (base: string, nom: string) => `${base.replace(/\/$/, '')}/${nom}`

  useEffect(() => {
    setLoading(true)
    ;(async () => {
      try {
        if (source.type === 'smb') setShares(await sourcesApi.shares(source.id))
        else setEntries(await sourcesApi.browse(source.id, '/'))
      } catch { toast.error('Exploration impossible') } finally { setLoading(false) }
    })()
  }, [source.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const naviguer = async (nouveauChemin: string, sharePick?: string) => {
    setLoading(true)
    try {
      const p = sharePick ?? partage ?? undefined
      const data = await sourcesApi.browse(source.id, nouveauChemin, p ?? undefined)
      setEntries(data); setChemin(nouveauChemin)
      if (sharePick) setPartage(sharePick)
    } catch { toast.error('Dossier illisible') } finally { setLoading(false) }
  }

  // Construit le préfixe de chemin scope à partir de l'emplacement courant.
  const choisir = () => {
    if (source.type === 'smb') {
      if (!partage) return
      const prefixe = `smb://${source.hote}/${partage}${chemin === '/' ? '' : chemin}`
      onPick(prefixe, `${partage}${chemin === '/' ? '' : chemin}`)
    } else {
      onPick(chemin, chemin)
    }
  }

  return (
    <div className="border border-blue-200 rounded-lg p-3 bg-blue-50/40">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium flex items-center gap-1.5">
          <FolderOpen size={15} className="text-blue-600" /> Choisir un dossier — {source.libelle}
        </span>
        <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700"><X size={15} /></button>
      </div>

      {/* SMB : choix du partage */}
      {source.type === 'smb' && !partage && (
        <div className="space-y-1">
          <p className="text-xs text-gray-500 mb-1">Partages disponibles :</p>
          {shares.map(sh => (
            <button key={sh} type="button" onClick={() => naviguer('/', sh)}
              className="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 rounded-md hover:bg-white border border-transparent hover:border-gray-200">
              <Server size={14} className="text-blue-600" /> {sh}
            </button>
          ))}
          {shares.length === 0 && !loading && <p className="text-xs text-gray-400">Aucun partage (ou identifiants requis).</p>}
        </div>
      )}

      {/* Navigation dossiers (local, ou SMB après choix du partage) */}
      {(source.type === 'local' || partage) && (
        <>
          <div className="flex items-center justify-between text-xs text-gray-500 mb-2 gap-2">
            <span className="font-mono truncate">{partage && `${partage} `}{chemin}</span>
            <button type="button" onClick={choisir}
              className="flex items-center gap-1 shrink-0 px-2.5 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-700">
              <Check size={13} /> Choisir ce dossier
            </button>
          </div>
          <div className="max-h-56 overflow-auto border border-gray-200 rounded-md bg-white divide-y divide-gray-50">
            {/* Remonter (ou revenir aux partages depuis la racine d'un partage SMB) */}
            {chemin !== '/' ? (
              <button type="button" onClick={() => naviguer(chemin.replace(/\/[^/]+\/?$/, '') || '/')}
                className="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 hover:bg-gray-50 text-gray-500">
                <ChevronRight size={13} className="rotate-180" /> ..
              </button>
            ) : source.type === 'smb' && (
              <button type="button" onClick={() => { setPartage(null); setEntries([]); setChemin('/') }}
                className="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 hover:bg-gray-50 text-gray-500">
                <ChevronRight size={13} className="rotate-180" /> Partages
              </button>
            )}
            {entries.filter(e => e.dossier).map(e => {
              const path = joinPath(chemin, e.nom)
              return (
                <button key={e.nom} type="button" onClick={() => naviguer(path)}
                  className="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 hover:bg-gray-50 min-w-0">
                  <Folder size={14} className="text-amber-500 shrink-0" />
                  <span className="truncate flex-1">{e.nom}</span>
                  <ChevronRight size={12} className="text-gray-300 shrink-0" />
                </button>
              )
            })}
            {entries.filter(e => e.dossier).length === 0 && !loading && (
              <p className="text-xs text-gray-400 px-2 py-2">Aucun sous-dossier — clique « Choisir ce dossier » pour prendre celui-ci.</p>
            )}
          </div>
        </>
      )}

      {loading && <p className="text-xs text-gray-400 mt-2 flex items-center gap-1"><RefreshCw size={12} className="animate-spin" /> Chargement…</p>}
    </div>
  )
}
