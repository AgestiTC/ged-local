/**
 * Page Liens documentaires — Matothèque
 * =====================================
 * Détecte et gère les liens entre documents partageant une **référence**
 * (BC ↔ facture, devis ↔ commande…). Flux : « Analyser » propose des paires →
 * l'utilisateur **valide** ou **rejette** → les liens validés font foi.
 *
 * Périmètre optionnel : restreindre l'analyse à un dossier (explorateur de source).
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Link2, Loader2, Check, X, Trash2, FolderSearch, Folder, ArrowLeftRight, FileText, Search,
} from 'lucide-react'
import { clsx } from 'clsx'
import { linksApi, sourcesApi, type DocumentLink, type Source } from '../api'
import SmbFolderPicker from '../components/ged/SmbFolderPicker'
import { useToast } from '../components/common/Toast'

type Onglet = 'suggere' | 'valide' | 'rejete'

const TYPE_LABEL: Record<string, string> = {
  bc_facture: 'BC ↔ facture',
  reference: 'même référence',
  manuel: 'lien manuel',
}

export default function LinksPage() {
  const toast = useToast()
  const [onglet, setOnglet] = useState<Onglet>('suggere')

  // Périmètre d'analyse
  const [sources, setSources] = useState<Source[]>([])
  const [sourceId, setSourceId] = useState('')
  const [prefixe, setPrefixe] = useState('')
  const [prefixeLabel, setPrefixeLabel] = useState('')
  const [showPicker, setShowPicker] = useState(false)
  const [scanning, setScanning] = useState(false)

  // Données
  const [liens, setLiens] = useState<DocumentLink[]>([])
  const [loading, setLoading] = useState(false)
  const [compte, setCompte] = useState<Record<Onglet, number>>({ suggere: 0, valide: 0, rejete: 0 })

  useEffect(() => { sourcesApi.list().then(setSources).catch(() => {}) }, [])

  const charger = async (o: Onglet) => {
    setLoading(true)
    try { setLiens((await linksApi.list(o)).liens) }
    catch { toast.error('Chargement des liens impossible') }
    finally { setLoading(false) }
  }
  useEffect(() => { charger(onglet) }, [onglet])

  // Compteurs par onglet (rafraîchis après chaque action)
  const rafraichirCompteurs = async () => {
    try {
      const [s, v, r] = await Promise.all([
        linksApi.list('suggere'), linksApi.list('valide'), linksApi.list('rejete'),
      ])
      setCompte({ suggere: s.nb, valide: v.nb, rejete: r.nb })
    } catch { /* silencieux */ }
  }
  useEffect(() => { rafraichirCompteurs() }, [])

  const analyser = async () => {
    setScanning(true)
    try {
      const r = await linksApi.scan(prefixe || undefined)
      if (r.nouvelles > 0) toast.success(`${r.nouvelles} nouveau(x) lien(s) proposé(s) sur ${r.documents_analyses} documents`)
      else toast.info(`Aucun nouveau lien (${r.documents_analyses} documents analysés, ${r.suggestions_trouvees} déjà connus)`)
      setOnglet('suggere'); await charger('suggere'); await rafraichirCompteurs()
    } catch { toast.error('Analyse impossible') } finally { setScanning(false) }
  }

  const agir = async (lien: DocumentLink, action: 'valide' | 'rejete' | 'suppr') => {
    try {
      if (action === 'valide') await linksApi.validate(lien.id)
      else if (action === 'rejete') await linksApi.reject(lien.id)
      else await linksApi.remove(lien.id)
      setLiens(ls => ls.filter(l => l.id !== lien.id))
      await rafraichirCompteurs()
    } catch { toast.error('Action impossible') }
  }

  const onglets: { k: Onglet; label: string }[] = [
    { k: 'suggere', label: 'À valider' },
    { k: 'valide', label: 'Validés' },
    { k: 'rejete', label: 'Rejetés' },
  ]

  const sourceCourante = useMemo(
    () => sources.find(s => s.id === sourceId) ?? sources[0],
    [sources, sourceId],
  )

  return (
    <div className="p-3 sm:p-6 max-w-4xl mx-auto">
      <div className="mb-4">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Link2 size={20} className="text-blue-600" /> Liens documentaires
        </h1>
        <p className="text-sm text-gray-500">
          Relie les documents partageant une référence (bon de commande ↔ facture, devis…). Les liens
          proposés sont à valider — rien n'est lié automatiquement.
        </p>
      </div>

      {/* Analyse */}
      <div className="bg-white border border-gray-200 rounded-lg p-3 space-y-3 mb-4">
        <div className="flex items-center gap-2 text-sm text-gray-600 flex-wrap">
          <Search size={15} className="text-blue-500 shrink-0" />
          <span className="shrink-0">Périmètre :</span>
          {prefixe ? (
            <span className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-blue-50 text-blue-700 border border-blue-200 text-xs min-w-0">
              <Folder size={12} className="shrink-0" />
              <span className="truncate font-mono" title={prefixe}>{prefixeLabel}</span>
              <button type="button" onClick={() => { setPrefixe(''); setPrefixeLabel('') }} title="Retirer" className="hover:text-blue-900 shrink-0">✕</button>
            </span>
          ) : (
            <span className="text-xs text-gray-400">tout l'index</span>
          )}
          {sources.length > 1 && !prefixe && (
            <select value={sourceId} onChange={e => setSourceId(e.target.value)}
              title="Source à explorer" className="text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white shrink-0">
              {sources.map(s => <option key={s.id} value={s.id}>{s.libelle}{s.hote ? ` (${s.hote})` : ''}</option>)}
            </select>
          )}
          {sources.length > 0 && (
            <button type="button" onClick={() => setShowPicker(v => !v)}
              className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 shrink-0">
              <FolderSearch size={14} /> {showPicker ? 'Fermer' : 'Cibler un dossier…'}
            </button>
          )}
          <button type="button" onClick={analyser} disabled={scanning}
            className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
            {scanning ? <Loader2 size={14} className="animate-spin" /> : <Link2 size={14} />}
            {scanning ? 'Analyse…' : 'Analyser les documents'}
          </button>
        </div>

        {showPicker && sources.length > 0 && sourceCourante && (
          <SmbFolderPicker
            source={sourceCourante}
            onPick={(p, label) => { setPrefixe(p); setPrefixeLabel(label); setShowPicker(false) }}
            onClose={() => setShowPicker(false)}
          />
        )}
        {scanning && (
          <p className="text-xs text-gray-400 flex items-center gap-1">
            <Loader2 size={12} className="animate-spin" /> Lecture des références dans le texte des documents…
          </p>
        )}
      </div>

      {/* Onglets */}
      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {onglets.map(o => (
          <button key={o.k} type="button" onClick={() => setOnglet(o.k)}
            className={clsx('px-3 py-2 text-sm border-b-2 -mb-px transition-colors flex items-center gap-1.5',
              onglet === o.k ? 'border-blue-600 text-blue-700 font-medium' : 'border-transparent text-gray-500 hover:text-gray-700')}>
            {o.label}
            <span className={clsx('text-xs px-1.5 py-0.5 rounded-full',
              onglet === o.k ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500')}>{compte[o.k]}</span>
          </button>
        ))}
      </div>

      {/* Liste */}
      {loading ? (
        <p className="text-sm text-gray-400 flex items-center gap-2 py-8 justify-center">
          <Loader2 size={16} className="animate-spin" /> Chargement…
        </p>
      ) : liens.length === 0 ? (
        <div className="text-center text-gray-400 py-10 text-sm">
          {onglet === 'suggere'
            ? 'Aucune suggestion. Lance « Analyser les documents » pour en détecter.'
            : onglet === 'valide' ? 'Aucun lien validé pour l\'instant.' : 'Aucun lien rejeté.'}
        </div>
      ) : (
        <ul className="space-y-2">
          {liens.map(l => (
            <li key={l.id} className="bg-white border border-gray-200 rounded-lg p-3">
              <div className="flex items-center gap-2 flex-wrap text-sm">
                <span className="flex items-center gap-1.5 min-w-0 max-w-[45%]">
                  <FileText size={14} className="text-gray-400 shrink-0" />
                  <span className="truncate font-medium text-gray-700" title={l.source.chemin ?? l.source.nom}>{l.source.nom}</span>
                </span>
                <ArrowLeftRight size={14} className="text-blue-500 shrink-0" />
                <span className="flex items-center gap-1.5 min-w-0 max-w-[45%]">
                  <FileText size={14} className="text-gray-400 shrink-0" />
                  <span className="truncate font-medium text-gray-700" title={l.cible.chemin ?? l.cible.nom}>{l.cible.nom}</span>
                </span>
              </div>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">
                  {TYPE_LABEL[l.type_lien] ?? l.type_lien}
                </span>
                {l.reference && (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-mono" title="Référence partagée">
                    {l.reference}
                  </span>
                )}
                {l.origine === 'auto' && (
                  <span className="text-xs text-gray-400">confiance {Math.round(l.score * 100)}%</span>
                )}

                <div className="ml-auto flex items-center gap-1.5">
                  {onglet === 'suggere' && (
                    <>
                      <button type="button" onClick={() => agir(l, 'valide')}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-green-600 text-white text-xs hover:bg-green-700">
                        <Check size={13} /> Valider
                      </button>
                      <button type="button" onClick={() => agir(l, 'rejete')}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 text-xs hover:bg-gray-50">
                        <X size={13} /> Rejeter
                      </button>
                    </>
                  )}
                  {onglet === 'valide' && (
                    <button type="button" onClick={() => agir(l, 'suppr')}
                      className="flex items-center gap-1 px-2.5 py-1 rounded-md border border-red-200 text-red-600 text-xs hover:bg-red-50">
                      <Trash2 size={13} /> Retirer
                    </button>
                  )}
                  {onglet === 'rejete' && (
                    <button type="button" onClick={() => agir(l, 'valide')}
                      className="flex items-center gap-1 px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 text-xs hover:bg-gray-50">
                      <Check size={13} /> Rétablir
                    </button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
