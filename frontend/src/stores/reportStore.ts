/**
 * Store Rapport — Zustand
 * ========================
 * Gère l'état de la génération de rapports :
 * prompt, modèle, mode de sortie, rapport en cours, historique.
 */

import { create } from 'zustand'
import type { OutputMode } from '../types'
import { generateApi, exportApi } from '../api'

interface ReportHistoryEntry {
  id: string
  prompt: string
  rapport: string
  model: string
  created_at: string
  nb_documents: number
}

interface ReportState {
  // Configuration
  prompt: string
  model: string
  outputMode: OutputMode

  // Génération en cours
  isGenerating: boolean
  jobId: string | null
  rapportEnCours: string   // Contenu streamé progressivement
  rapportFinal: string     // Rapport complet une fois terminé
  error: string | null

  // Historique local (session)
  historique: ReportHistoryEntry[]

  // Actions
  setPrompt: (p: string) => void
  setModel: (m: string) => void
  setOutputMode: (mode: OutputMode) => void

  startGeneration: (documentIds: string[]) => Promise<void>
  appendChunk: (chunk: string) => void
  finishGeneration: (rapportComplet: string) => void
  cancelGeneration: () => void
  resetRapport: () => void

  exportPdf: (title?: string) => Promise<void>
  exportDocx: (title?: string) => Promise<void>
}

export const useReportStore = create<ReportState>((set, get) => ({
  prompt: '',
  model: 'mixtral:latest',
  outputMode: 'rapport_libre',
  isGenerating: false,
  jobId: null,
  rapportEnCours: '',
  rapportFinal: '',
  error: null,
  historique: [],

  setPrompt: (prompt) => set({ prompt }),
  setModel: (model) => set({ model }),
  setOutputMode: (outputMode) => set({ outputMode }),

  startGeneration: async (documentIds) => {
    const { prompt, model } = get()
    if (!prompt.trim()) return

    set({ isGenerating: true, rapportEnCours: '', rapportFinal: '', error: null, jobId: null })

    try {
      const response = await generateApi.startReport({
        document_ids: documentIds,
        prompt,
        model,
        output_format: 'markdown',
      })

      set({ jobId: response.job_id })

      // Ouvrir le flux SSE
      const streamUrl = generateApi.getStreamUrl(response.job_id)
      const eventSource = new EventSource(streamUrl)

      eventSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as { chunk: string; done: boolean; rapport_complet?: string; erreur?: string }

          if (data.done) {
            eventSource.close()
            const rapport = data.rapport_complet || get().rapportEnCours
            get().finishGeneration(rapport)
          } else if (data.chunk) {
            get().appendChunk(data.chunk)
          }
        } catch { /* ignorer les lignes malformées */ }
      }

      eventSource.onerror = () => {
        eventSource.close()
        set({ isGenerating: false, error: 'Connexion au flux interrompue' })
      }
    } catch (e: unknown) {
      set({
        isGenerating: false,
        error: e instanceof Error ? e.message : 'Erreur lancement génération',
      })
    }
  },

  appendChunk: (chunk) =>
    set(s => ({ rapportEnCours: s.rapportEnCours + chunk })),

  finishGeneration: (rapportComplet) => {
    const { prompt, model } = get()
    const entry: ReportHistoryEntry = {
      id: crypto.randomUUID(),
      prompt,
      rapport: rapportComplet,
      model,
      created_at: new Date().toISOString(),
      nb_documents: 0,
    }
    set(s => ({
      isGenerating: false,
      rapportFinal: rapportComplet,
      rapportEnCours: rapportComplet,
      historique: [entry, ...s.historique].slice(0, 20), // Garder 20 entrées max
    }))
  },

  cancelGeneration: () => set({ isGenerating: false, error: 'Génération annulée' }),

  resetRapport: () => set({ rapportEnCours: '', rapportFinal: '', error: null, jobId: null }),

  exportPdf: async (title) => {
    const rapport = get().rapportFinal || get().rapportEnCours
    if (!rapport) return
    await exportApi.toPdf(rapport, title || 'Rapport DocFlow AI')
  },

  exportDocx: async (title) => {
    const rapport = get().rapportFinal || get().rapportEnCours
    if (!rapport) return
    await exportApi.toDocx(rapport, title || 'Rapport DocFlow AI')
  },
}))
