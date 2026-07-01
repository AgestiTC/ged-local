/**
 * Page GED — Recherche hybride + panneau latéral fiche document
 * Barre de recherche + filtres + grille de résultats + panneau détail
 */
import { useEffect, useRef, useState } from 'react'
import { Search, X, Tag, FolderOpen, FileText, List, Eye, Download, Copy, Trash2, FolderMinus, Loader2, MonitorPlay } from 'lucide-react'
import { clsx } from 'clsx'
import { useNavigate } from 'react-router-dom'
import { useGEDStore } from '../stores/gedStore'
import { useDocumentStore } from '../stores/documentStore'
import { useGedSelection } from '../stores/gedSelectionStore'
import DocumentCard from '../components/ged/DocumentCard'
import DocumentPreview from '../components/ged/DocumentPreview'
import AllDocumentsView, { type QuickFilter, type Mode } from '../components/ged/AllDocumentsView'
import LoadingSpinner from '../components/common/LoadingSpinner'
import { documentsApi, corbeilleApi, presentationsApi, suivreJob } from '../api'
import { useToast } from '../components/common/Toast'
import type { SearchType, Document } from '../types'

function formatBytes(n?: number) {
  if (!n) return ''
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} Ko`
  return `${(n / 1024 / 1024).toFixed(1)} Mo`
}

const SEARCH_TYPES: { value: SearchType; label: string }[] = [
  { value: 'hybrid', label: 'Hybride' },
  { value: 'text', label: 'Texte' },
  { value: 'semantic', label: 'Sémantique' },
]

export default function GEDPage() {
  const {
    query, searchType,
    results, total, hasMore, loadingMore, loading, error,
    categories, tags,
    setQuery, setSearchType,
    search, loadMore, clearResults,
    loadTags, loadCategories,
  } = useGEDStore()

  const { selectDocument } = useDocumentStore()
  const navigate = useNavigate()
  const toast = useToast()
  const inputRef = useRef<HTMLInputElement>(null)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [preview, setPreview] = useState<Document | null>(null)  // aperçu fichier (résultats de recherche)

  const telecharger = (id: string, nom: string) => {
    const a = document.createElement('a'); a.href = documentsApi.fileUrl(id, true); a.download = nom; a.click()
  }
  const copierChemin = async (chemin?: string) => {
    if (!chemin) { toast.error('Chemin indisponible'); return }
    try { await navigator.clipboard.writeText(chemin); toast.success('Chemin copié') } catch { toast.error('Copie impossible') }
  }

  // ── Sélection multiple + actions de masse ──
  const selection = useGedSelection()
  const [bulkAction, setBulkAction] = useState<'corbeille' | 'desindexer' | null>(null)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)  // remonte AllDocumentsView après une action de masse
  const [creatingPres, setCreatingPres] = useState(false)

  const creerPresentation = async () => {
    const ids = [...selection.ids]
    if (ids.length < 2) return
    setCreatingPres(true)
    try {
      // Tâche durable : on met en file puis on suit le job (survit au changement de page).
      const { job_id } = await presentationsApi.creer(ids)
      const job = await suivreJob(job_id)
      if (job.statut === 'completed') {
        const r = job.resultat as { presentation_id?: string; titre?: string; nb_slides?: number } | null
        if (r?.presentation_id) {
          window.open(`/presentation/${r.presentation_id}`, '_blank', 'noopener')
          toast.success(`Présentation « ${r.titre ?? ''} » créée (${r.nb_slides ?? 0} diapos)`)
          selection.clear()
        }
      } else if (job.statut === 'failed') {
        toast.error(`Génération impossible : ${job.erreur ?? 'Ollama ?'}`)
      }
    } catch {
      toast.error('Génération de la présentation impossible (Ollama ?)')
    } finally { setCreatingPres(false) }
  }

  const confirmerBulk = async () => {
    const ids = [...selection.ids]
    if (ids.length === 0) { setBulkAction(null); return }
    setBulkBusy(true)
    let ok = 0, ko = 0
    for (const id of ids) {
      try {
        if (bulkAction === 'corbeille') await corbeilleApi.envoyer(id)
        else await documentsApi.delete(id)
        ok++
      } catch { ko++ }
    }
    setBulkBusy(false)
    setBulkAction(null)
    selection.clear()
    setRefreshKey(k => k + 1)        // rafraîchit la liste « Tout afficher »
    if (!showAll && query) search()  // rafraîchit les résultats de recherche
    const verbe = bulkAction === 'corbeille' ? 'déplacé(s) vers la corbeille' : 'retiré(s) de l\'index'
    ok && toast.success(`${ok} fichier(s) ${verbe}`)
    ko && toast.error(`${ko} échec(s)`)
  }

  // GED « parcourable par défaut » : on ouvre sur la liste (Tout afficher), pas sur une recherche vide.
  const [showAll, setShowAll] = useState(true)
  // Filtre rapide piloté par le rail (catégorie/tag), appliqué à la liste sans requête.
  const [quickFilter, setQuickFilter] = useState<QuickFilter | null>(null)
  // Mode de regroupement (remonté d'AllDocumentsView) — sert à masquer le rail Catégories/Tags
  // quand on regroupe déjà (évite le doublon).
  const [groupBy, setGroupBy] = useState<Mode>('none')
  const toutAfficher = () => { setShowAll(true); setQuickFilter(null); setSelectedDocId(null); clearResults() }

  useEffect(() => {
    loadTags()
    loadCategories()
  }, [])

  // Lancer une recherche → bascule en mode résultats (quitte le mode parcourir)
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setShowAll(false); setQuickFilter(null)
    search()
  }

  // Rail : filtrer la liste par catégorie/tag (mode parcourir), sans recherche
  const filtrerCategorie = (categorie: string) => {
    setQuery(''); clearResults(); setSelectedDocId(null)
    setShowAll(true); setQuickFilter({ categorie })
  }
  const filtrerTag = (tag: string) => {
    setQuery(''); clearResults(); setSelectedDocId(null)
    setShowAll(true); setQuickFilter({ tag })
  }

  const handleUseInReport = (id: string) => {
    selectDocument(id)
    navigate('/')
  }

  return (
    <div className="flex h-full overflow-hidden">

      {/* ── Filtres (masqués quand on regroupe déjà : doublon avec « Grouper par ») ── */}
      <aside className="w-48 shrink-0 bg-white border-r border-gray-200 p-3 overflow-y-auto flex flex-col gap-4">

        {/* Catégories */}
        {groupBy === 'none' && categories.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Catégories</h3>
            <div className="flex flex-col gap-0.5">
              {quickFilter?.categorie && (
                <button
                  onClick={() => setQuickFilter(null)}
                  className="text-left text-xs px-2.5 py-1.5 rounded-md text-blue-600 bg-blue-50 flex items-center justify-between"
                >
                  <span className="truncate">{quickFilter.categorie}</span>
                  <X size={10} />
                </button>
              )}
              {categories.slice(0, 12).filter(c => c.categorie !== quickFilter?.categorie).map(c => (
                <button
                  key={c.categorie}
                  onClick={() => filtrerCategorie(c.categorie)}
                  className="text-left text-xs px-2.5 py-1.5 rounded-md text-gray-600 hover:bg-gray-50 flex items-center justify-between"
                >
                  <span className="truncate">{c.categorie}</span>
                  <span className="text-gray-400 shrink-0">{c.nb_documents}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Tags */}
        {groupBy === 'none' && tags.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Tags</h3>
            <div className="flex flex-wrap gap-1">
              {tags.slice(0, 20).map(t => (
                <button
                  key={t.tag}
                  onClick={() => filtrerTag(t.tag)}
                  className={clsx(
                    'text-xs px-2 py-0.5 rounded-full transition-colors',
                    quickFilter?.tag === t.tag
                      ? 'bg-blue-100 text-blue-700 font-medium'
                      : 'bg-gray-100 hover:bg-blue-50 hover:text-blue-700 text-gray-600',
                  )}
                >
                  {t.tag}
                </button>
              ))}
            </div>
          </div>
        )}

        {groupBy !== 'none' && (
          <p className="text-xs text-gray-400 leading-relaxed">
            Vue groupée par <strong>{groupBy}</strong> active. Repasse « Grouper par&nbsp;: Aucun »
            pour filtrer par catégorie ou tag ici.
          </p>
        )}
      </aside>

      {/* ── Zone principale ──────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">

        {/* Barre de recherche */}
        <div className="bg-white border-b border-gray-200 p-3">
          <form onSubmit={handleSearch} className="flex gap-2">
            <div className="flex-1 relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                ref={inputRef}
                type="search"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Rechercher dans vos documents…"
                className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400"
                autoFocus
              />
            </div>
            <button
              type="submit"
              disabled={!query.trim() || loading}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg disabled:opacity-40 transition-colors"
            >
              Rechercher
            </button>
            <button
              type="button"
              onClick={toutAfficher}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-lg border transition-colors',
                showAll ? 'bg-blue-50 text-blue-700 border-blue-300' : 'text-gray-600 border-gray-200 hover:bg-gray-50',
              )}
              title="Voir tous les documents indexés"
            >
              <List size={14} /> Tout afficher
            </button>
            {(results.length > 0 || query) && (
              <button
                type="button"
                onClick={() => { setQuery(''); clearResults(); setSelectedDocId(null); setShowAll(true) }}
                className="px-3 py-2 text-gray-400 hover:text-gray-700 border border-gray-200 rounded-lg"
                title="Effacer et revenir à la liste"
              >
                <X size={14} />
              </button>
            )}
          </form>

          {/* Mode de recherche (à côté de la recherche, plutôt qu'en colonne) */}
          <div className="flex items-center gap-1.5 mt-2 text-xs text-gray-500">
            <span>Recherche :</span>
            {SEARCH_TYPES.map(t => (
              <button
                key={t.value}
                type="button"
                onClick={() => setSearchType(t.value)}
                className={clsx(
                  'px-2 py-0.5 rounded-md transition-colors',
                  searchType === t.value ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-500 hover:bg-gray-50',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Résultats */}
        <div className="flex-1 overflow-y-auto p-3">

          {/* ── Mode parcourir (liste + vue groupée + filtre rapide) ── */}
          {showAll && (
            <AllDocumentsView
              key={refreshKey}
              filter={quickFilter}
              onClearFilter={() => setQuickFilter(null)}
              groupBy={groupBy}
              onGroupByChange={setGroupBy}
            />
          )}

          {!showAll && loading && (
            <div className="flex justify-center py-12">
              <LoadingSpinner label="Recherche en cours…" />
            </div>
          )}

          {!showAll && error && <p className="text-sm text-red-500 py-4 text-center">{error}</p>}

          {!showAll && !loading && results.length === 0 && query && (
            <p className="text-sm text-gray-400 py-12 text-center">Aucun résultat pour « {query} »</p>
          )}

          {!showAll && !loading && results.length === 0 && !query && (
            <div className="flex flex-col items-center justify-center py-16 text-gray-300 gap-3">
              <Search size={44} strokeWidth={1} />
              <p className="text-sm">Recherche hybride full-text + sémantique</p>
              <p className="text-xs">Importez des documents puis lancez une recherche</p>
            </div>
          )}

          {!showAll && results.length > 0 && (
            <>
              <p className="text-xs text-gray-500 mb-3">
                {total} résultat{total > 1 ? 's' : ''} — mode {searchType}
              </p>
              <div className={clsx(
                'grid gap-2',
                selectedDocId ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3',
              )}>
                {results.map(r => (
                  <div
                    key={r.id}
                    onClick={() => setSelectedDocId(r.id === selectedDocId ? null : r.id)}
                    className={clsx(
                      'bg-white border rounded-lg p-3 cursor-pointer transition-all hover:shadow-sm',
                      r.id === selectedDocId ? 'border-blue-400 shadow-sm' : 'border-gray-200 hover:border-blue-300',
                    )}
                  >
                    <div className="flex items-start gap-2 mb-2">
                      <input type="checkbox" checked={selection.has(r.id)} onClick={e => e.stopPropagation()}
                        onChange={() => selection.toggle(r.id)} className="w-4 h-4 accent-amber-600 mt-0.5 shrink-0"
                        aria-label={`Sélectionner ${r.nom}`} />
                      <FileText size={15} className="text-gray-400 mt-0.5 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-800 truncate" title={r.nom}>{r.nom}</p>
                        <p className="text-xs text-gray-400">{r.extension.toUpperCase()} · {formatBytes(r.taille_octets)}</p>
                      </div>
                      <span className="text-xs text-blue-600 font-semibold shrink-0">
                        {(r.score * 100).toFixed(0)}%
                      </span>
                    </div>

                    {r.metadonnees_ia.resume && (
                      <p className="text-xs text-gray-600 line-clamp-2 mb-2 leading-relaxed">
                        {r.metadonnees_ia.resume}
                      </p>
                    )}

                    <div className="flex flex-wrap gap-1">
                      {r.metadonnees_ia.categorie && (
                        <span className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded-full flex items-center gap-1">
                          <FolderOpen size={9} />{r.metadonnees_ia.categorie}
                        </span>
                      )}
                      {r.metadonnees_ia.tags.slice(0, 3).map(tag => (
                        <span key={tag} className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded-full flex items-center gap-1">
                          <Tag size={9} />{tag}
                        </span>
                      ))}
                    </div>

                    {/* Actions (cohérence avec la vue « Tout afficher ») */}
                    <div className="flex items-center gap-1 mt-2 pt-2 border-t border-gray-100" onClick={e => e.stopPropagation()}>
                      <button type="button" title="Aperçu du fichier"
                        onClick={() => setPreview({ id: r.id, nom: r.nom, extension: r.extension, chemin: '', chemin_copie: r.chemin_copie } as Document)}
                        className="flex items-center gap-1 text-xs px-2 py-1 text-blue-600 hover:bg-blue-50 rounded">
                        <Eye size={13} /> Aperçu
                      </button>
                      <button type="button" title="Fiche IA" onClick={() => setSelectedDocId(r.id)}
                        className="flex items-center gap-1 text-xs px-2 py-1 text-violet-600 hover:bg-violet-50 rounded">
                        <FileText size={13} /> Fiche
                      </button>
                      <button type="button" title="Télécharger" onClick={() => telecharger(r.id, r.nom)}
                        className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded">
                        <Download size={13} />
                      </button>
                      <button type="button" title="Copier le chemin (UNC)" onClick={() => copierChemin(r.chemin_copie)}
                        className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded">
                        <Copy size={13} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              {/* Charger plus */}
              {hasMore && (
                <div className="flex justify-center mt-4">
                  <button
                    onClick={loadMore}
                    disabled={loadingMore}
                    className="flex items-center gap-2 px-5 py-2 text-sm text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 disabled:opacity-40 transition-colors"
                  >
                    {loadingMore ? (
                      <LoadingSpinner size={14} />
                    ) : null}
                    {loadingMore ? 'Chargement…' : 'Charger plus de résultats'}
                  </button>
                </div>
              )}

              {!hasMore && total > 20 && (
                <p className="text-xs text-gray-400 text-center mt-4">
                  Tous les {total} résultats sont affichés
                </p>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Panneau latéral fiche document ───────────────── */}
      {selectedDocId && (
        <div className="w-80 shrink-0 overflow-hidden border-l border-gray-200">
          <DocumentCard
            documentId={selectedDocId}
            onClose={() => setSelectedDocId(null)}
            onUseInReport={handleUseInReport}
          />
        </div>
      )}

      {/* Aperçu fichier (depuis un résultat de recherche) */}
      {preview && <DocumentPreview doc={preview} onClose={() => setPreview(null)} />}

      {/* Barre d'actions de masse (sélection multiple) */}
      {selection.ids.size > 0 && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 bg-gray-900 text-white rounded-xl shadow-lg px-4 py-2.5 flex items-center gap-3">
          <span className="text-sm font-medium">{selection.ids.size} sélectionné{selection.ids.size > 1 ? 's' : ''}</span>
          <button type="button" onClick={() => selection.clear()} className="text-xs text-gray-300 hover:text-white">Tout désélectionner</button>
          <span className="w-px h-5 bg-gray-700" />
          {selection.ids.size >= 2 && (
            <button type="button" onClick={creerPresentation} disabled={creatingPres}
              className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-700 disabled:opacity-60"
              title="Générer une présentation (diaporama IA) à partir des fichiers sélectionnés">
              {creatingPres ? <Loader2 size={15} className="animate-spin" /> : <MonitorPlay size={15} />}
              {creatingPres ? 'Génération…' : 'Créer une présentation'}
            </button>
          )}
          <button type="button" onClick={() => setBulkAction('desindexer')}
            className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg hover:bg-gray-800">
            <FolderMinus size={15} /> Désindexer
          </button>
          <button type="button" onClick={() => setBulkAction('corbeille')}
            className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg bg-red-600 hover:bg-red-700">
            <Trash2 size={15} /> Corbeille
          </button>
        </div>
      )}

      {/* Confirmation action de masse */}
      {bulkAction && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => !bulkBusy && setBulkAction(null)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2">
              {bulkAction === 'corbeille' ? <Trash2 size={18} className="text-red-600" /> : <FolderMinus size={18} className="text-gray-600" />}
              {bulkAction === 'corbeille' ? 'Déplacer vers la corbeille' : 'Retirer de l\'index'}
            </h2>
            <p className="text-sm text-gray-600 mb-4">
              <strong>{selection.ids.size}</strong> fichier(s) vont être {bulkAction === 'corbeille'
                ? <>déplacés vers <strong>A-SUPPRIMER-MATOTEQUE</strong> (les fichiers ne sont <strong>pas supprimés</strong>, restaurables)</>
                : <>retirés de l'index (les <strong>fichiers du NAS ne sont pas touchés</strong>)</>}.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setBulkAction(null)} disabled={bulkBusy}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">Annuler</button>
              <button type="button" onClick={confirmerBulk} disabled={bulkBusy}
                className={clsx('flex items-center gap-2 px-4 py-2 text-white text-sm rounded-lg disabled:opacity-50',
                  bulkAction === 'corbeille' ? 'bg-red-600 hover:bg-red-700' : 'bg-gray-800 hover:bg-gray-900')}>
                {bulkBusy ? <Loader2 size={16} className="animate-spin" /> : null} Confirmer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
