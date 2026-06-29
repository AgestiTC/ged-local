/**
 * Store de sélection multiple GED — Zustand
 * =========================================
 * Sélection de fichiers transverse à la GED (vue cartes, vue liste, résultats de
 * recherche). Sert aux actions de masse (corbeille, désindexer…) et, à terme, à
 * la création de présentations (≥ 2 fichiers).
 */
import { create } from 'zustand'

interface GedSelectionState {
  ids: Set<string>
  toggle: (id: string) => void
  add: (ids: string[]) => void
  clear: () => void
  has: (id: string) => boolean
}

export const useGedSelection = create<GedSelectionState>((set, get) => ({
  ids: new Set(),
  toggle: (id) => set(s => {
    const n = new Set(s.ids)
    n.has(id) ? n.delete(id) : n.add(id)
    return { ids: n }
  }),
  add: (ids) => set(s => ({ ids: new Set([...s.ids, ...ids]) })),
  clear: () => set({ ids: new Set() }),
  has: (id) => get().ids.has(id),
}))
