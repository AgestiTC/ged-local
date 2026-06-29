/**
 * Store Assistant Rapport — Zustand
 * =================================
 * État levé de l'Assistant « Trouver des documents » : le besoin saisi et les
 * pièces proposées par l'IA. Partagé entre l'INPUT (étape ② de la page Rapports)
 * et l'AFFICHAGE des propositions dans le panneau « Résultat ».
 */
import { create } from 'zustand'
import { assistantApi, type PieceProposee } from '../api'

interface ReportAssistantState {
  besoin: string
  loading: boolean
  pieces: PieceProposee[] | null

  setBesoin: (v: string) => void
  /** Lance la déduction des pièces. Retourne le nombre total de fichiers proposés (ou null si besoin trop court). */
  proposer: () => Promise<number | null>
  clear: () => void
}

export const useReportAssistantStore = create<ReportAssistantState>((set, get) => ({
  besoin: '',
  loading: false,
  pieces: null,

  setBesoin: (besoin) => set({ besoin }),

  proposer: async () => {
    const besoin = get().besoin.trim()
    if (besoin.length < 3) return null
    set({ loading: true, pieces: null })
    try {
      const r = await assistantApi.pieces(besoin)
      set({ pieces: r.pieces, loading: false })
      return r.pieces.reduce((n, p) => n + p.documents.length, 0)
    } catch (e) {
      set({ loading: false })
      throw e
    }
  },

  clear: () => set({ pieces: null }),
}))
