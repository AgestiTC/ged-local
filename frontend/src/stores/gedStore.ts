/**
 * Store GED — Zustand
 * ====================
 * Gère l'état de la recherche et des résultats de la GED.
 */

import { create } from 'zustand'
import type { SearchFilters, SearchType } from '../types'
import { searchApi, type SearchResponse } from '../api'

const PAGE_SIZE = 20

interface GEDState {
  query: string
  searchType: SearchType
  filters: SearchFilters
  results: SearchResponse['resultats']
  total: number
  hasMore: boolean
  currentOffset: number
  loading: boolean
  loadingMore: boolean
  error: string | null
  tags: Array<{ tag: string; nb_documents: number }>
  categories: Array<{ categorie: string; nb_documents: number }>

  setQuery: (q: string) => void
  setSearchType: (type: SearchType) => void
  setFilters: (filters: SearchFilters) => void
  search: () => Promise<void>
  loadMore: () => Promise<void>
  clearResults: () => void
  loadTags: () => Promise<void>
  loadCategories: () => Promise<void>
}

export const useGEDStore = create<GEDState>((set, get) => ({
  query: '',
  searchType: 'hybrid',
  filters: {},
  results: [],
  total: 0,
  hasMore: false,
  currentOffset: 0,
  loading: false,
  loadingMore: false,
  error: null,
  tags: [],
  categories: [],

  setQuery: (query) => set({ query }),
  setSearchType: (searchType) => set({ searchType }),
  setFilters: (filters) => set({ filters }),

  search: async () => {
    const { query, searchType, filters } = get()
    if (!query.trim()) return

    set({ loading: true, error: null, currentOffset: 0 })
    try {
      const data = await searchApi.search({
        q: query,
        type: searchType,
        limit: PAGE_SIZE,
        offset: 0,
        categorie: filters.categorie,
        extension: filters.extension,
      })
      set({
        results: data.resultats,
        total: data.total,
        hasMore: data.has_more,
        currentOffset: PAGE_SIZE,
        loading: false,
      })
    } catch (e: unknown) {
      set({ error: e instanceof Error ? e.message : 'Erreur recherche', loading: false })
    }
  },

  loadMore: async () => {
    const { query, searchType, filters, currentOffset, loadingMore, hasMore, results } = get()
    if (!query.trim() || loadingMore || !hasMore) return

    set({ loadingMore: true })
    try {
      const data = await searchApi.search({
        q: query,
        type: searchType,
        limit: PAGE_SIZE,
        offset: currentOffset,
        categorie: filters.categorie,
        extension: filters.extension,
      })
      set({
        results: [...results, ...data.resultats],
        total: data.total,
        hasMore: data.has_more,
        currentOffset: currentOffset + PAGE_SIZE,
        loadingMore: false,
      })
    } catch {
      set({ loadingMore: false })
    }
  },

  clearResults: () => set({ results: [], total: 0, query: '', hasMore: false, currentOffset: 0 }),

  loadTags: async () => {
    try {
      const data = await searchApi.getTags()
      set({ tags: data.tags })
    } catch { /* silencieux */ }
  },

  loadCategories: async () => {
    try {
      const data = await searchApi.getCategories()
      set({ categories: data.categories })
    } catch { /* silencieux */ }
  },
}))
