/**
 * Hook useSearch — wrapper fin sur gedStore
 * Expose la recherche hybride GED + pagination "load more".
 */
import { useGEDStore } from '../stores/gedStore'

export function useSearch() {
  const {
    query, searchType, filters,
    results, total, hasMore, currentOffset, loading, loadingMore, error,
    tags, categories,
    setQuery, setSearchType, setFilters,
    search, loadMore, clearResults,
    loadTags, loadCategories,
  } = useGEDStore()

  return {
    query,
    searchType,
    filters,
    results,
    total,
    hasMore,
    currentOffset,
    loading,
    loadingMore,
    error,
    tags,
    categories,
    setQuery,
    setSearchType,
    setFilters,
    search,
    loadMore,
    clearResults,
    loadTags,
    loadCategories,
  }
}
