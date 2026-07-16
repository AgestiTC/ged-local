/**
 * IndexedDocsTree — picker « Parcourir » de la page Créer, en ARBORESCENCE.
 * Remplace la liste plate (« X sur N doc(s) ») par un arbre de dossiers à la
 * `IndexedFolders`, mais dont les FEUILLES sont les fichiers cochables → sélection
 * du rapport (`documentStore`). Chargement PARESSEUX par dossier (`/documents/tree`).
 * Le filtre bascule sur une recherche PLATE transverse (comportement de l'ancien picker).
 */
import { useEffect, useState } from 'react'
import { Folder, FolderOpen, ChevronRight, ChevronDown, FileText, Loader2, RefreshCw, Search } from 'lucide-react'
import { clsx } from 'clsx'
import { documentsApi, type TreeNode, type TreeFile } from '../../api'
import { useDocumentStore } from '../../stores/documentStore'
import { useToast } from '../common/Toast'
import type { Document } from '../../types'

function formatBytes(n?: number) {
  if (!n) return ''
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} Ko`
  return `${(n / 1024 / 1024).toFixed(1)} Mo`
}

type Level = { dossiers: TreeNode[]; fichiers: TreeFile[] }

export default function IndexedDocsTree() {
  const toast = useToast()
  const { selectedIds, selectMany, toggleSelect, isSelected, deselectAll } = useDocumentStore()

  const [cache, setCache] = useState<Record<string, Level>>({})
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState<Set<string>>(new Set())
  const [rootLoading, setRootLoading] = useState(true)

  const [filter, setFilter] = useState('')
  const [flatDocs, setFlatDocs] = useState<Document[]>([])
  const [flatLoading, setFlatLoading] = useState(false)

  const loadLevel = async (prefixe: string, force = false) => {
    if (cache[prefixe] && !force) return
    setLoading(s => new Set(s).add(prefixe))
    try {
      const d = await documentsApi.tree(prefixe)
      setCache(c => ({ ...c, [prefixe]: { dossiers: d.dossiers, fichiers: d.fichiers } }))
    } catch {
      toast.error('Chargement de l\'arborescence impossible')
    } finally {
      setLoading(s => { const n = new Set(s); n.delete(prefixe); return n })
    }
  }

  useEffect(() => { loadLevel('').finally(() => setRootLoading(false)) }, [])

  // Filtre → recherche PLATE transverse (sur TOUS les indexés porteurs de texte). Débounce.
  useEffect(() => {
    if (!filter.trim()) { setFlatDocs([]); return }
    const t = setTimeout(async () => {
      setFlatLoading(true)
      try {
        const r = await documentsApi.list({ texte: true, q: filter.trim(), page: 1, page_size: 100 })
        setFlatDocs(r.documents)
      } catch { /* silencieux */ } finally { setFlatLoading(false) }
    }, 300)
    return () => clearTimeout(t)
  }, [filter])

  const toggleExpand = (chemin: string) => {
    setExpanded(s => {
      const n = new Set(s)
      if (n.has(chemin)) n.delete(chemin)
      else { n.add(chemin); loadLevel(chemin) }
      return n
    })
  }

  // Coche TOUS les fichiers sous un dossier (récursif, via /documents/tree?flat=true).
  const cocherDossier = async (chemin: string) => {
    try {
      const files = await documentsApi.treeFlat(chemin)
      if (files.length === 0) { toast.error('Aucun fichier avec texte sous ce dossier'); return }
      selectMany(files.map(f => f.id))
      toast.success(`${files.length} fichier(s) coché(s)`)
    } catch { toast.error('Sélection du dossier impossible') }
  }

  // ── Rendu d'un niveau (récursif) ──
  const renderLevel = (prefixe: string, niveau: number) => {
    const data = cache[prefixe]
    if (!data) return null
    return (
      <>
        {data.dossiers.map(d => {
          const ouvert = expanded.has(d.chemin)
          const enCours = loading.has(d.chemin)
          return (
            <div key={d.chemin}>
              <div className="flex items-center gap-1.5 py-1 hover:bg-gray-50 rounded text-xs" style={{ paddingLeft: `${niveau * 14}px` }}>
                <button type="button" onClick={() => toggleExpand(d.chemin)} className="text-gray-400 shrink-0 w-4">
                  {enCours ? <Loader2 size={12} className="animate-spin" /> : ouvert ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                </button>
                {ouvert ? <FolderOpen size={13} className="text-amber-500 shrink-0" /> : <Folder size={13} className="text-amber-500 shrink-0" />}
                <button type="button" onClick={() => toggleExpand(d.chemin)} className="flex-1 min-w-0 text-left truncate text-gray-700">
                  {d.nom}
                </button>
                <span className="text-gray-400 shrink-0">{d.nb}</span>
                <button type="button" onClick={() => cocherDossier(d.chemin)} title="Cocher tous les fichiers de ce dossier"
                  className="text-[10px] px-1.5 py-0.5 rounded text-blue-600 hover:bg-blue-50 shrink-0">tout cocher</button>
              </div>
              {ouvert && renderLevel(d.chemin, niveau + 1)}
            </div>
          )
        })}
        {data.fichiers.map(f => (
          <div key={f.id} onClick={() => toggleSelect(f.id)}
            className={clsx('flex items-start gap-2 py-1 pr-1 rounded cursor-pointer text-xs',
              isSelected(f.id) ? 'bg-blue-50' : 'hover:bg-gray-50')}
            style={{ paddingLeft: `${niveau * 14 + 6}px` }}>
            <input type="checkbox" checked={isSelected(f.id)} onChange={() => toggleSelect(f.id)} onClick={e => e.stopPropagation()}
              className="w-3.5 h-3.5 accent-blue-600 mt-0.5 shrink-0" aria-label={`Sélectionner ${f.nom}`} />
            <FileText size={12} className="text-gray-400 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="truncate font-medium text-gray-700">{f.nom}</p>
              <p className="text-gray-400">{f.extension.toUpperCase()} · {formatBytes(f.taille_octets)}</p>
            </div>
          </div>
        ))}
      </>
    )
  }

  return (
    <div className="flex flex-col h-full gap-2">
      {/* En-tête */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500 font-medium">
          {selectedIds.size > 0 ? `${selectedIds.size} sélectionné(s)` : 'Parcourir les dossiers indexés'}
        </span>
        <div className="flex items-center gap-2">
          {selectedIds.size > 0 && (
            <button type="button" onClick={deselectAll} className="text-xs text-gray-500 hover:text-gray-700">Tout désélectionner</button>
          )}
          <button type="button" onClick={() => { setCache({}); setExpanded(new Set()); setRootLoading(true); loadLevel('', true).finally(() => setRootLoading(false)) }}
            className="text-gray-400 hover:text-gray-600" title="Actualiser"><RefreshCw size={13} /></button>
        </div>
      </div>

      {/* Filtre (bascule en recherche plate) */}
      <div className="relative">
        <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" />
        <input type="search" placeholder="Filtrer par nom (cherche dans tous)…" value={filter}
          onChange={e => setFilter(e.target.value)}
          className="w-full pl-7 pr-2 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400" />
      </div>

      {/* Corps */}
      <div className="flex-1 overflow-y-auto min-h-0 -mr-1 pr-1">
        {filter.trim() ? (
          // Mode recherche plate
          <>
            {flatLoading && <p className="text-xs text-gray-400 py-3 flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Recherche…</p>}
            {!flatLoading && flatDocs.length === 0 && <p className="text-xs text-gray-400 py-3 text-center">Aucun document pour « {filter} ».</p>}
            {flatDocs.map(d => (
              <div key={d.id} onClick={() => toggleSelect(d.id)}
                className={clsx('flex items-start gap-2 py-1 px-1 rounded cursor-pointer text-xs',
                  isSelected(d.id) ? 'bg-blue-50' : 'hover:bg-gray-50')}>
                <input type="checkbox" checked={isSelected(d.id)} onChange={() => toggleSelect(d.id)} onClick={e => e.stopPropagation()}
                  className="w-3.5 h-3.5 accent-blue-600 mt-0.5 shrink-0" aria-label={`Sélectionner ${d.nom}`} />
                <FileText size={12} className="text-gray-400 mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="truncate font-medium text-gray-700">{d.nom}</p>
                  <p className="text-gray-400">{d.extension.toUpperCase()} · {formatBytes(d.taille_octets)}</p>
                </div>
              </div>
            ))}
          </>
        ) : rootLoading ? (
          <p className="text-xs text-gray-400 py-3 flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Chargement…</p>
        ) : (cache['']?.dossiers.length ?? 0) === 0 ? (
          <p className="text-xs text-gray-400 py-3 text-center">Aucun document indexé.</p>
        ) : (
          renderLevel('', 0)
        )}
      </div>
    </div>
  )
}
