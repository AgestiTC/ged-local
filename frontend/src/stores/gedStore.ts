/**
 * Store GED — Zustand
 * TODO Phase 3
 */
import { create } from 'zustand'
import type { SearchFilters, SearchType } from '../types'

interface GEDStore {
  query: string
  searchType: SearchType
  filters: SearchFilters
  setQuery: (query: string) => void
  setSearchType: (type: SearchType) => void
  setFilters: (filters: SearchFilters) => void
}

export const useGEDStore = create<GEDStore>((set) => ({
  query: '',
  searchType: 'hybrid',
  filters: {},
  setQuery: (query) => set({ query }),
  setSearchType: (searchType) => set({ searchType }),
  setFilters: (filters) => set({ filters }),
}))
