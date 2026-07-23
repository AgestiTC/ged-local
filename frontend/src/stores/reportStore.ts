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
  startedAt: number | null // horodatage du lancement (chrono d'avancement)
  // Instantané de la préparation, FIGÉ au lancement : la check-list « Votre rapport » ne doit
  // pas se recalculer pendant la génération (ex. si l'utilisateur décoche un document).
  prepSnapshot: { nbDocs: number; mode: OutputMode; promptDefini: boolean } | null

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
  editRapport: (text: string) => void
  loadRapport: (contenu: string) => void

  exportPdf: (title?: string) => Promise<void>
  exportDocx: (title?: string) => Promise<void>
  exportMarkdown: (title?: string) => void
}

export const useReportStore = create<ReportState>((set, get) => ({
  prompt: '',
  // '' = « Auto » : on n'impose AUCUN modèle → le backend route selon la config par usage
  // (Paramètres → Services & modèles IA : « routage dynamique, Auto = défaut »).
  // Ne JAMAIS figer un nom de modèle ici : le front n'a aucune raison de savoir ce qui est
  // installé, et une valeur en dur survit à la suppression du modèle (bug « mixtral »).
  model: '',
  outputMode: 'rapport_libre',
  isGenerating: false,
  jobId: null,
  rapportEnCours: '',
  rapportFinal: '',
  error: null,
  startedAt: null,
  prepSnapshot: null,
  historique: [],

  setPrompt: (prompt) => set({ prompt }),
  setModel: (model) => set({ model }),
  setOutputMode: (outputMode) => set({ outputMode }),

  startGeneration: async (documentIds) => {
    const { prompt, model, outputMode } = get()
    if (!prompt.trim()) return

    set({
      isGenerating: true, rapportEnCours: '', rapportFinal: '', error: null, jobId: null,
      startedAt: Date.now(),
      prepSnapshot: { nbDocs: documentIds.length, mode: outputMode, promptDefini: !!prompt.trim() },
    })

    try {
      const response = await generateApi.startReport({
        document_ids: documentIds,
        prompt,
        model,
        output_format: 'markdown',
        mode: outputMode,
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

  resetRapport: () => set({ rapportEnCours: '', rapportFinal: '', error: null, jobId: null, startedAt: null, prepSnapshot: null }),

  // Édition inline du résultat (avant export / publication wiki)
  editRapport: (text) => set({ rapportEnCours: text, rapportFinal: text }),

  // Charge un rapport de l'historique dans le panneau (comme s'il venait d'être généré).
  loadRapport: (contenu) => set({
    rapportEnCours: contenu, rapportFinal: contenu,
    isGenerating: false, error: null, jobId: null,
  }),

  exportPdf: async (title) => {
    const rapport = get().rapportFinal || get().rapportEnCours
    if (!rapport) return
    await exportApi.toPdf(rapport, title || 'Rapport Matothèque')
  },

  exportDocx: async (title) => {
    const rapport = get().rapportFinal || get().rapportEnCours
    if (!rapport) return
    await exportApi.toDocx(rapport, title || 'Rapport Matothèque')
  },

  // Le contenu EST déjà du Markdown → téléchargement direct côté navigateur, aucun appel backend.
  exportMarkdown: (title) => {
    const rapport = get().rapportFinal || get().rapportEnCours
    if (!rapport) return
    const nom = (title || 'Rapport Matothèque').replace(/[^\w\-. ]+/g, '_').trim() || 'rapport'
    const blob = new Blob([rapport], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${nom}.md`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  },
}))
