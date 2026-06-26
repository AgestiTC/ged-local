/**
 * Page GED — Recherche hybride + panneau latéral fiche document
 * Barre de recherche + filtres + grille de résultats + panneau détail
 */
import { useEffect, useRef, useState } from 'react'
import { Search, X, Tag, FolderOpen, FileText, List } from 'lucide-react'
import { clsx } from 'clsx'
import { useNavigate } from 'react-router-dom'
import { useGEDStore } from '../stores/gedStore'
import { useDocumentStore } from '../stores/documentStore'
import DocumentCard from '../components/ged/DocumentCard'
import AllDocumentsView from '../components/ged/AllDocumentsView'
import DropZone from '../components/files/DropZone'
import LoadingSpinner from '../components/common/LoadingSpinner'
import type { SearchType } from '../types'

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
    query, searchType, filters,
    results, total, hasMore, loadingMore, loading, error,
    categories, tags,
    setQuery, setSearchType, setFilters,
    search, loadMore, clearResults,
    loadTags, loadCategories,
  } = useGEDStore()

  const { selectDocument } = useDocumentStore()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)

  // Mode « Tout afficher » : liste/regroupe tous les documents indexés (cf. AllDocumentsView)
  const [showAll, setShowAll] = useState(false)
  const toutAfficher = () => { setShowAll(v => !v); setSelectedDocId(null) }

  useEffect(() => {
    loadTags()
    loadCategories()
  }, [])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    search()
  }

  const handleUseInReport = (id: string) => {
    selectDocument(id)
    navigate('/')
  }

  return (
    <div className="flex h-full overflow-hidden">

      {/* ── Filtres ──────────────────────────────────────── */}
      <aside className="w-48 shrink-0 bg-white border-r border-gray-200 p-3 overflow-y-auto flex flex-col gap-4">
        {/* Import GED */}
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Importer</h3>
          <DropZone compact />
        </div>

        {/* Type de recherche */}
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Mode</h3>
          <div className="flex flex-col gap-0.5">
            {SEARCH_TYPES.map(t => (
              <button
                key={t.value}
                onClick={() => setSearchType(t.value)}
                className={clsx(
                  'text-left text-xs px-2.5 py-1.5 rounded-md transition-colors',
                  searchType === t.value ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-600 hover:bg-gray-50',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Catégories */}
        {categories.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Catégories</h3>
            <div className="flex flex-col gap-0.5">
              {filters.categorie && (
                <button
                  onClick={() => { setFilters({ ...filters, categorie: undefined }); search() }}
                  className="text-left text-xs px-2.5 py-1.5 rounded-md text-blue-600 bg-blue-50 flex items-center justify-between"
                >
                  <span className="truncate">{filters.categorie}</span>
                  <X size={10} />
                </button>
              )}
              {categories.slice(0, 12).filter(c => c.categorie !== filters.categorie).map(c => (
                <button
                  key={c.categorie}
                  onClick={() => { setFilters({ ...filters, categorie: c.categorie }); search() }}
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
        {tags.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Tags</h3>
            <div className="flex flex-wrap gap-1">
              {tags.slice(0, 20).map(t => (
                <button
                  key={t.tag}
                  onClick={() => { setQuery(t.tag); search() }}
                  className="text-xs px-2 py-0.5 bg-gray-100 hover:bg-blue-50 hover:text-blue-700 rounded-full text-gray-600 transition-colors"
                >
                  {t.tag}
                </button>
              ))}
            </div>
          </div>
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
                onClick={() => { clearResults(); setSelectedDocId(null) }}
                className="px-3 py-2 text-gray-400 hover:text-gray-700 border border-gray-200 rounded-lg"
                title="Effacer"
              >
                <X size={14} />
              </button>
            )}
          </form>
        </div>

        {/* Résultats */}
        <div className="flex-1 overflow-y-auto p-3">

          {/* ── Mode « Tout afficher » (liste + vue groupée) ── */}
          {showAll && <AllDocumentsView />}

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
    </div>
  )
}
