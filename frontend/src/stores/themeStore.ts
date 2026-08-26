/**
 * Store Thème — clair / sombre (Zustand + persist)
 * ================================================
 * Bascule le thème de l'app en (dé)posant la classe `dark` sur <html> (Tailwind `darkMode:'class'`).
 * Persisté en localStorage → le choix survit au rechargement. Un mini-script dans `index.html`
 * applique la classe AVANT le rendu pour éviter le flash clair au chargement.
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'light' | 'dark'

function appliquer(t: Theme) {
  document.documentElement.classList.toggle('dark', t === 'dark')
}

interface ThemeState {
  theme: Theme
  toggle: () => void
  setTheme: (t: Theme) => void
}

export const useThemeStore = create<ThemeState>()(persist(
  (set, get) => ({
    theme: 'light',
    toggle: () => { const t: Theme = get().theme === 'dark' ? 'light' : 'dark'; appliquer(t); set({ theme: t }) },
    setTheme: (t) => { appliquer(t); set({ theme: t }) },
  }),
  {
    name: 'matotheque-theme',
    // Applique le thème restauré après réhydratation (cohérence si le script inline a manqué).
    onRehydrateStorage: () => (state) => { if (state) appliquer(state.theme) },
  },
))
