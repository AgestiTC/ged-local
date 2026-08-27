/**
 * Store Préférences Wiki (Zustand + persist)
 * ==========================================
 * Préférences d'affichage du menu Wiki, persistées en localStorage (100% local).
 * - `shelvesCollapsedDefault` : les sections d'étagères démarrent-elles repliées ?
 *   (l'utilisateur peut toujours replier/déplier chaque section à la main ensuite).
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface WikiPrefsState {
  shelvesCollapsedDefault: boolean
  setShelvesCollapsedDefault: (v: boolean) => void
}

export const useWikiPrefsStore = create<WikiPrefsState>()(persist(
  (set) => ({
    shelvesCollapsedDefault: false,
    setShelvesCollapsedDefault: (v) => set({ shelvesCollapsedDefault: v }),
  }),
  { name: 'matotheque-wiki-prefs' },
))
