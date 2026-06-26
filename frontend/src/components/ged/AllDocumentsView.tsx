/**
 * AllDocumentsView — « Tout afficher » dans la GED
 * ================================================
 * Liste tous les documents indexés sans recherche, en vue plate OU groupée
 * (par extension / catégorie IA / tag). Chaque carte : aperçu, télécharger,
 * copier le chemin (UNC). Les groupes se chargent à l'ouverture (lazy).
 */
import { useCallback, useEffect, useState } from 'react'
import { FileText, FolderOpen, Eye, Download, Copy, ChevronRight, ChevronDown, Tag as TagIcon, X, Sparkles, Trash2, Loader2, Undo2, LayoutGrid, List as ListIcon } from 'lucide-react'
import { clsx } from 'clsx'
import { documentsApi, corbeilleApi, type GroupBy, type DocumentGroup } from '../../api'
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

export type Mode = 'none' | GroupBy

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

export default function AllDocumentsView({ filter = null, onClearFilter, groupBy, onGroupByChange }: {
  filter?: QuickFilter | null
  onClearFilter?: () => void
  groupBy?: Mode                       // mode de regroupement contrôlé (sinon état interne)
  onGroupByChange?: (m: Mode) => void
}) {
  const toast = useToast()
  const [modeLocal, setModeLocal] = useState<Mode>('none')
  const mode = groupBy ?? modeLocal
  const setMode = onGroupByChange ?? setModeLocal
  const [preview, setPreview] = useState<Document | null>(null)
  const [fiche, setFiche] = useState<string | null>(null)  // id du doc dont on ouvre la fiche IA
  // Corbeille : doc en attente de confirmation, ids masqués (déplacés), bandeau d'annulation
  const [corbeilleCible, setCorbeilleCible] = useState<Document | null>(null)
  const [masques, setMasques] = useState<Set<string>>(new Set())
  const [annulable, setAnnulable] = useState<{ cid: string; nom: string } | null>(null)
  const [corbeilleEnCours, setCorbeilleEnCours] = useState(false)
  const [vue, setVue] = useState<'cartes' | 'liste'>('cartes')  // bascule cartes ⇄ liste

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

  // Corbeille : déplace le fichier (après confirmation) → masque la carte + bandeau « Annuler »
  const confirmerCorbeille = async () => {
    if (!corbeilleCible) return
    const d = corbeilleCible
    setCorbeilleEnCours(true)
    try {
      const r = await corbeilleApi.envoyer(d.id)
      setMasques(p => new Set(p).add(d.id))
      setAnnulable({ cid: r.corbeille_id, nom: r.nom })
      setCorbeilleCible(null)
      toast.success(`« ${r.nom} » déplacé vers la corbeille`)
    } catch {
      toast.error('Déplacement vers la corbeille impossible')
    } finally { setCorbeilleEnCours(false) }
  }

  const annulerCorbeille = async () => {
    if (!annulable) return
    const a = annulable
    setAnnulable(null)
    try {
      await corbeilleApi.restaurer(a.cid)
      toast.success(`« ${a.nom} » restauré`)
      if (flat) chargerPlat(1)  // recharge pour refaire apparaître le doc restauré
    } catch {
      toast.error('Restauration impossible')
    }
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
      {/* Bascule cartes ⇄ liste */}
      <div className="flex items-center justify-end mb-2">
        <div className="inline-flex rounded-md border border-gray-200 overflow-hidden">
          <button type="button" onClick={() => setVue('cartes')} title="Vue cartes"
            className={clsx('p-1.5', vue === 'cartes' ? 'bg-blue-50 text-blue-700' : 'text-gray-400 hover:bg-gray-50')}>
            <LayoutGrid size={15} />
          </button>
          <button type="button" onClick={() => setVue('liste')} title="Vue liste"
            className={clsx('p-1.5 border-l border-gray-200', vue === 'liste' ? 'bg-blue-50 text-blue-700' : 'text-gray-400 hover:bg-gray-50')}>
            <ListIcon size={15} />
          </button>
        </div>
      </div>

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
              <Grid docs={docs.filter(d => !masques.has(d.id))} vue={vue} onPreview={setPreview} onDownload={telecharger} onCopy={copier} onFiche={setFiche} onCorbeille={setCorbeilleCible} />
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
                          <Grid docs={bucket.docs.filter(d => !masques.has(d.id))} vue={vue} onPreview={setPreview} onDownload={telecharger} onCopy={copier} onFiche={setFiche} onCorbeille={setCorbeilleCible} />
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

      {/* Confirmation « déplacer vers la corbeille » (Annuler / Confirmer) */}
      {corbeilleCible && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => !corbeilleEnCours && setCorbeilleCible(null)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2"><Trash2 size={18} className="text-red-600" /> Déplacer vers la corbeille</h2>
            <p className="text-sm text-gray-600 mb-4">
              <strong className="break-all">{corbeilleCible.nom}</strong> va être déplacé dans le dossier
              <strong> A-SUPPRIMER-MATOTEQUE</strong> sur la source. Le fichier n'est <strong>pas supprimé</strong> —
              tu pourras l'annuler / le restaurer.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setCorbeilleCible(null)} disabled={corbeilleEnCours}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">Annuler</button>
              <button type="button" onClick={confirmerCorbeille} disabled={corbeilleEnCours}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50">
                {corbeilleEnCours ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />} Confirmer
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bandeau d'annulation après déplacement */}
      {annulable && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 bg-gray-900 text-white text-sm rounded-lg shadow-lg px-4 py-2.5 flex items-center gap-3">
          <span>« {annulable.nom} » déplacé vers la corbeille</span>
          <button type="button" onClick={annulerCorbeille} className="flex items-center gap-1 font-medium text-amber-300 hover:text-amber-200">
            <Undo2 size={14} /> Annuler
          </button>
          <button type="button" onClick={() => setAnnulable(null)} title="Fermer" className="text-gray-400 hover:text-white"><X size={14} /></button>
        </div>
      )}

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

interface GridHandlers {
  onPreview: (d: Document) => void
  onDownload: (d: Document) => void
  onCopy: (d: Document) => void
  onFiche: (id: string) => void
  onCorbeille: (d: Document) => void
}

/** Barre d'actions d'un document (réutilisée carte + ligne). */
function DocActions({ d, h, showLabels }: { d: Document; h: GridHandlers; showLabels?: boolean }) {
  return (
    <>
      <button type="button" onClick={() => h.onPreview(d)} title="Aperçu du fichier"
        className="flex items-center gap-1 text-xs px-2 py-1 text-blue-600 hover:bg-blue-50 rounded">
        <Eye size={13} />{showLabels && ' Aperçu'}
      </button>
      <button type="button" onClick={() => h.onFiche(d.id)} title="Fiche IA : résumé, catégorie, tags (éditables), entités"
        className="flex items-center gap-1 text-xs px-2 py-1 text-violet-600 hover:bg-violet-50 rounded">
        <Sparkles size={13} />{showLabels && ' Fiche'}
      </button>
      <button type="button" onClick={() => h.onDownload(d)} title="Télécharger l'original"
        className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded">
        <Download size={13} />
      </button>
      <button type="button" onClick={() => h.onCopy(d)} title="Copier le chemin (UNC)"
        className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded">
        <Copy size={13} />
      </button>
      <button type="button" onClick={() => h.onCorbeille(d)} title="Déplacer vers la corbeille (À supprimer)"
        className="flex items-center gap-1 text-xs px-2 py-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded">
        <Trash2 size={13} />
      </button>
    </>
  )
}

function Grid({ docs, vue, ...h }: { docs: Document[]; vue: 'cartes' | 'liste' } & GridHandlers) {
  // ── Vue liste (lignes compactes) ──
  if (vue === 'liste') {
    return (
      <div className="border border-gray-200 rounded-lg bg-white divide-y divide-gray-100">
        {docs.map(d => (
          <div key={d.id} className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50">
            <FileText size={14} className="text-gray-400 shrink-0" />
            <span className="text-sm text-gray-800 truncate flex-1 min-w-0" title={d.nom}>{d.nom}</span>
            {d.metadonnees_ia?.categorie && (
              <span className="hidden md:inline text-xs px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded-full shrink-0">{d.metadonnees_ia.categorie}</span>
            )}
            <span className="text-xs text-gray-400 shrink-0 w-28 text-right">{d.extension.toUpperCase()} · {formatBytes(d.taille_octets)}</span>
            <div className="flex items-center gap-0.5 shrink-0"><DocActions d={d} h={h} /></div>
          </div>
        ))}
      </div>
    )
  }

  // ── Vue cartes ──
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
            <DocActions d={d} h={h} showLabels />
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
