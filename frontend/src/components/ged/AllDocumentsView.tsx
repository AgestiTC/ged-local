/**
 * AllDocumentsView — « Tout afficher » dans la GED
 * ================================================
 * Liste tous les documents indexés sans recherche, en vue plate OU groupée
 * (par extension / catégorie IA / tag). Chaque carte : aperçu, télécharger,
 * copier le chemin (UNC). Les groupes se chargent à l'ouverture (lazy).
 */
import { useCallback, useEffect, useState } from 'react'
import { FileText, FolderOpen, Eye, Download, Copy, ChevronRight, ChevronDown, Tag as TagIcon, X, Sparkles } from 'lucide-react'
import { clsx } from 'clsx'
import { documentsApi, type GroupBy, type DocumentGroup } from '../../api'
import { useToast } from '../common/Toast'
import LoadingSpinner from '../common/LoadingSpinner'
import DocumentPreview from './DocumentPreview'
import DocumentCard from './DocumentCard'
import type { Document } from '../../types'

const PAGE = 30

function formatBytes(n?: number) {
  if (!n) return ''
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} Ko`
  return `${(n / 1024 / 1024).toFixed(1)} Mo`
}

type Mode = 'none' | GroupBy

const MODES: { value: Mode; label: string }[] = [
  { value: 'none', label: 'Aucun' },
  { value: 'extension', label: 'Extension' },
  { value: 'categorie', label: 'Catégorie' },
  { value: 'tag', label: 'Tag' },
]

/** Clé/filtre d'un groupe selon le mode. */
function groupKey(by: GroupBy, valeur: string | null): string {
  return valeur ?? (by === 'categorie' ? '__sans__' : '?')
}
function groupLabel(valeur: string | null): string {
  return valeur ?? '(non classé)'
}
function groupFilter(by: GroupBy, valeur: string | null) {
  const v = groupKey(by, valeur)
  return by === 'extension' ? { extension: v } : by === 'tag' ? { tag: v } : { categorie: v }
}

interface Bucket { docs: Document[]; total: number; page: number; loading: boolean; open: boolean }

/** Filtre rapide piloté depuis le rail (catégorie ou tag) — force la vue plate filtrée. */
export interface QuickFilter { categorie?: string; tag?: string }

export default function AllDocumentsView({ filter = null, onClearFilter }: {
  filter?: QuickFilter | null
  onClearFilter?: () => void
}) {
  const toast = useToast()
  const [mode, setMode] = useState<Mode>('none')
  const [preview, setPreview] = useState<Document | null>(null)
  const [fiche, setFiche] = useState<string | null>(null)  // id du doc dont on ouvre la fiche IA

  // Vue plate
  const [docs, setDocs] = useState<Document[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  // Vue groupée
  const [groups, setGroups] = useState<DocumentGroup[]>([])
  const [loadingGroups, setLoadingGroups] = useState(false)
  const [buckets, setBuckets] = useState<Record<string, Bucket>>({})

  const copier = async (d: Document) => {
    try { await navigator.clipboard.writeText(d.chemin_copie || d.chemin); toast.success('Chemin copié') }
    catch { toast.error('Copie impossible') }
  }
  const telecharger = (d: Document) => {
    const a = document.createElement('a')
    a.href = documentsApi.fileUrl(d.id, true); a.download = d.nom; a.click()
  }

  // ── Vue plate (avec filtre rapide éventuel) ──
  const chargerPlat = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const r = await documentsApi.list({ page: p, page_size: PAGE, ...(filter ?? {}) })
      setTotal(r.total); setPage(p)
      setDocs(prev => (p === 1 ? r.documents : [...prev, ...r.documents]))
    } catch { toast.error('Impossible de charger les documents') }
    finally { setLoading(false) }
  }, [toast, filter])

  // ── Vue groupée ──
  const chargerGroupes = useCallback(async (by: GroupBy) => {
    setLoadingGroups(true); setBuckets({})
    try { setGroups((await documentsApi.groups(by)).groupes) }
    catch { toast.error('Impossible de charger les groupes') }
    finally { setLoadingGroups(false) }
  }, [toast])

  // Un filtre rapide (rail) force la vue plate filtrée ; sinon mode plat/groupé normal.
  const flat = !!filter || mode === 'none'
  useEffect(() => {
    if (flat) chargerPlat(1)
    else chargerGroupes(mode)
  }, [mode, filter]) // eslint-disable-line react-hooks/exhaustive-deps

  const chargerBucket = async (by: GroupBy, g: DocumentGroup, p: number) => {
    const key = groupKey(by, g.valeur)
    setBuckets(b => ({ ...b, [key]: { ...(b[key] ?? { docs: [], total: g.nb, page: 0, open: true }), loading: true, open: true } }))
    try {
      const r = await documentsApi.list({ ...groupFilter(by, g.valeur), page: p, page_size: PAGE })
      setBuckets(b => {
        const cur = b[key] ?? { docs: [], total: g.nb, page: 0, open: true, loading: false }
        return { ...b, [key]: { docs: p === 1 ? r.documents : [...cur.docs, ...r.documents], total: r.total, page: p, loading: false, open: true } }
      })
    } catch {
      toast.error('Impossible de charger ce groupe')
      setBuckets(b => ({ ...b, [key]: { ...(b[key] as Bucket), loading: false } }))
    }
  }

  const toggleBucket = (by: GroupBy, g: DocumentGroup) => {
    const key = groupKey(by, g.valeur)
    const cur = buckets[key]
    if (cur?.open) { setBuckets(b => ({ ...b, [key]: { ...cur, open: false } })); return }
    if (cur && cur.docs.length > 0) { setBuckets(b => ({ ...b, [key]: { ...cur, open: true } })); return }
    chargerBucket(by, g, 1)
  }

  return (
    <div>
      {/* Bandeau « filtré par » (catégorie/tag depuis le rail) */}
      {filter && (
        <div className="flex items-center gap-2 mb-3 text-xs">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
            {filter.tag ? <TagIcon size={12} /> : <FolderOpen size={12} />}
            Filtré : <strong>{filter.categorie ?? filter.tag}</strong>
            <button type="button" onClick={onClearFilter} className="ml-0.5 hover:text-blue-900" title="Retirer le filtre">
              <X size={12} />
            </button>
          </span>
        </div>
      )}

      {/* Sélecteur de regroupement (masqué quand un filtre rapide est actif) */}
      {!filter && (
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <span className="text-xs text-gray-500">Grouper par :</span>
          {MODES.map(m => (
            <button key={m.value} type="button" onClick={() => setMode(m.value)}
              className={clsx('text-xs px-2.5 py-1 rounded-md border transition-colors',
                mode === m.value ? 'bg-blue-50 text-blue-700 border-blue-300' : 'text-gray-600 border-gray-200 hover:bg-gray-50')}>
              {m.label}
            </button>
          ))}
        </div>
      )}

      {/* ── Vue plate (tout, ou filtrée par catégorie/tag) ── */}
      {flat && (
        <>
          <p className="text-xs text-gray-500 mb-3">{total} document{total > 1 ? 's' : ''}{filter ? '' : ' indexé' + (total > 1 ? 's' : '')}</p>
          {loading && docs.length === 0 ? (
            <div className="flex justify-center py-12"><LoadingSpinner label="Chargement…" /></div>
          ) : docs.length === 0 ? (
            <p className="text-sm text-gray-400 py-12 text-center">{filter ? 'Aucun document pour ce filtre.' : 'Aucun document indexé.'}</p>
          ) : (
            <>
              <Grid docs={docs} onPreview={setPreview} onDownload={telecharger} onCopy={copier} onFiche={setFiche} />
              {docs.length < total && (
                <ChargerPlus loading={loading} onClick={() => chargerPlat(page + 1)} label={`Charger plus (${docs.length}/${total})`} />
              )}
            </>
          )}
        </>
      )}

      {/* ── Vue groupée ── */}
      {!flat && (
        loadingGroups ? (
          <div className="flex justify-center py-12"><LoadingSpinner label="Chargement des groupes…" /></div>
        ) : groups.length === 0 ? (
          <p className="text-sm text-gray-400 py-12 text-center">Aucun groupe.</p>
        ) : (
          <div className="space-y-1.5">
            <p className="text-xs text-gray-500 mb-2">{groups.length} groupe{groups.length > 1 ? 's' : ''}</p>
            {groups.map(g => {
              const key = groupKey(mode, g.valeur)
              const bucket = buckets[key]
              return (
                <div key={key} className="border border-gray-200 rounded-lg overflow-hidden">
                  <button type="button" onClick={() => toggleBucket(mode, g)}
                    className="flex items-center gap-2 w-full px-3 py-2 text-left text-sm hover:bg-gray-50">
                    {bucket?.open ? <ChevronDown size={14} className="text-gray-400 shrink-0" /> : <ChevronRight size={14} className="text-gray-400 shrink-0" />}
                    {mode === 'tag' ? <TagIcon size={14} className="text-gray-400 shrink-0" /> : <FolderOpen size={14} className="text-amber-500 shrink-0" />}
                    <span className={clsx('font-medium flex-1 truncate', g.valeur === null && 'text-gray-400 italic')}>
                      {mode === 'extension' && g.valeur ? g.valeur.toUpperCase() : groupLabel(g.valeur)}
                    </span>
                    <span className="text-xs text-gray-400 shrink-0">{g.nb}</span>
                  </button>
                  {bucket?.open && (
                    <div className="border-t border-gray-100 p-2 bg-gray-50/40">
                      {bucket.loading && bucket.docs.length === 0 ? (
                        <div className="flex justify-center py-6"><LoadingSpinner size={16} /></div>
                      ) : (
                        <>
                          <Grid docs={bucket.docs} onPreview={setPreview} onDownload={telecharger} onCopy={copier} onFiche={setFiche} />
                          {bucket.docs.length < bucket.total && (
                            <ChargerPlus loading={bucket.loading} onClick={() => chargerBucket(mode, g, bucket.page + 1)}
                              label={`Charger plus (${bucket.docs.length}/${bucket.total})`} />
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )
      )}

      {preview && <DocumentPreview doc={preview} onClose={() => setPreview(null)} />}

      {/* Tiroir fiche IA (résumé, catégorie, entités, tags éditables) */}
      {fiche && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={() => setFiche(null)}>
          <div className="w-[380px] max-w-full h-full bg-white shadow-xl" onClick={e => e.stopPropagation()}>
            <DocumentCard documentId={fiche} onClose={() => setFiche(null)} />
          </div>
        </div>
      )}
    </div>
  )
}

// ── Sous-composants ──

function Grid({ docs, onPreview, onDownload, onCopy, onFiche }: {
  docs: Document[]
  onPreview: (d: Document) => void
  onDownload: (d: Document) => void
  onCopy: (d: Document) => void
  onFiche: (id: string) => void
}) {
  return (
    <div className="grid gap-2 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
      {docs.map(d => (
        <div key={d.id} className="bg-white border border-gray-200 rounded-lg p-3 hover:shadow-sm hover:border-blue-300 transition-all">
          <div className="flex items-start gap-2 mb-2">
            <FileText size={15} className="text-gray-400 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate" title={d.nom}>{d.nom}</p>
              <p className="text-xs text-gray-400">{d.extension.toUpperCase()} · {formatBytes(d.taille_octets)}</p>
            </div>
          </div>
          {d.metadonnees_ia?.categorie && (
            <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded-full mb-2">
              <FolderOpen size={9} />{d.metadonnees_ia.categorie}
            </span>
          )}
          <div className="flex items-center gap-1 pt-1 border-t border-gray-100">
            <button type="button" onClick={() => onPreview(d)} title="Aperçu du fichier"
              className="flex items-center gap-1 text-xs px-2 py-1 text-blue-600 hover:bg-blue-50 rounded">
              <Eye size={13} /> Aperçu
            </button>
            <button type="button" onClick={() => onFiche(d.id)} title="Fiche IA : résumé, catégorie, tags (éditables), entités"
              className="flex items-center gap-1 text-xs px-2 py-1 text-violet-600 hover:bg-violet-50 rounded">
              <Sparkles size={13} /> Fiche
            </button>
            <button type="button" onClick={() => onDownload(d)} title="Télécharger l'original"
              className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded">
              <Download size={13} />
            </button>
            <button type="button" onClick={() => onCopy(d)} title="Copier le chemin (UNC)"
              className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded">
              <Copy size={13} />
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

function ChargerPlus({ loading, onClick, label }: { loading: boolean; onClick: () => void; label: string }) {
  return (
    <div className="flex justify-center mt-3">
      <button type="button" onClick={onClick} disabled={loading}
        className="flex items-center gap-2 px-5 py-2 text-sm text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 disabled:opacity-40">
        {loading ? <LoadingSpinner size={14} /> : null}
        {loading ? 'Chargement…' : label}
      </button>
    </div>
  )
}
