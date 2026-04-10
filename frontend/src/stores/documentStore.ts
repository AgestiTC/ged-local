/**
 * Store documents — Zustand
 * TODO Phase 2 : état global des documents sélectionnés
 */
import { create } from 'zustand'
import type { Document } from '../types'

interface DocumentStore {
  selectedIds: string[]
  documents: Document[]
  select: (id: string) => void
  deselect: (id: string) => void
  selectAll: (ids: string[]) => void
  clearSelection: () => void
}

export const useDocumentStore = create<DocumentStore>((set) => ({
  selectedIds: [],
  documents: [],
  select: (id) => set((s) => ({ selectedIds: [...s.selectedIds, id] })),
  deselect: (id) => set((s) => ({ selectedIds: s.selectedIds.filter((i) => i !== id) })),
  selectAll: (ids) => set({ selectedIds: ids }),
  clearSelection: () => set({ selectedIds: [] }),
}))
