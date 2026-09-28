/**
 * Store Documents — Zustand
 * ==========================
 * Gère la liste des documents, la sélection multi-fichiers,
 * et le suivi des uploads/jobs en cours.
 */

import { create } from 'zustand'
import type { Document } from '../types'
import { documentsApi, extractApi, uploadApi } from '../api'

interface UploadJob {
  fichier: string
  job_id?: string
  statut: 'en_attente' | 'running' | 'completed' | 'failed' | 'rejeté' | 'erreur'
  progress?: number
  /** Pourquoi le suivi s'est arrêté sans réponse du serveur (coupure, délai dépassé). */
  raison?: string
}

// Suivi d'un upload : au-delà de N échecs d'affilée (≈ 30 s) ou du plafond d'essais, on le DIT
// au lieu de laisser le badge « en cours » à vie (audit du 28/09/2026, M10).
const ECHECS_SUIVI_MAX = 6
const ESSAIS_SUIVI_MAX = 120

interface DocumentState {
  documents: Document[]
  total: number
  page: number
  loading: boolean
  error: string | null
  selectedIds: Set<string>
  /**
   * Métadonnées des documents cochés depuis l'ARBRE (page Créer), qui ne passent jamais par
   * `fetchDocuments` et sont donc absents de `documents`. Sans ce registre, tout calcul basé
   * sur la sélection (estimation du contexte…) voyait « 0 document » alors que plusieurs
   * étaient cochés. Alimenté à la sélection, jamais purgé (quelques octets par entrée).
   */
  metaSelection: Record<string, { nom: string; taille_octets?: number; texte_longueur?: number }>
  uploadJobs: UploadJob[]

  /** Mémorise les métadonnées de documents connus hors `documents` (picker en arbre). */
  memoriserMeta: (docs: Array<{ id: string; nom: string; taille_octets?: number; texte_longueur?: number }>) => void
  fetchDocuments: (params?: { page?: number; page_size?: number; q?: string; statut?: string; extension?: string; texte?: boolean }) => Promise<void>
  selectDocument: (id: string) => void
  deselectDocument: (id: string) => void
  selectMany: (ids: string[]) => void
  deselectMany: (ids: string[]) => void
  selectAll: () => void
  deselectAll: () => void
  toggleSelect: (id: string) => void
  isSelected: (id: string) => boolean
  uploadFiles: (files: File[], folderTag?: string) => Promise<void>
  deleteDocument: (id: string) => Promise<void>
  relaunchExtraction: (id: string) => Promise<void>
  pollJobStatus: (jobId: string) => void
  clearUploadJobs: () => void
}

export const useDocumentStore = create<DocumentState>((set, get) => ({
  documents: [],
  total: 0,
  page: 1,
  loading: false,
  error: null,
  selectedIds: new Set(),
  metaSelection: {},
  uploadJobs: [],

  memoriserMeta: (docs) => set(s => {
    const next = { ...s.metaSelection }
    for (const d of docs) next[d.id] = { nom: d.nom, taille_octets: d.taille_octets, texte_longueur: d.texte_longueur }
    return { metaSelection: next }
  }),

  fetchDocuments: async (params) => {
    set({ loading: true, error: null })
    try {
      const data = await documentsApi.list({ page: get().page, page_size: 50, ...params })
      set({ documents: data.documents, total: data.total, page: data.page, loading: false })
    } catch (e: unknown) {
      set({ error: e instanceof Error ? e.message : 'Erreur chargement', loading: false })
    }
  },

  selectDocument: (id) => set(s => ({ selectedIds: new Set([...s.selectedIds, id]) })),

  selectMany: (ids) => set(s => ({ selectedIds: new Set([...s.selectedIds, ...ids]) })),

  deselectMany: (ids) => set(s => {
    const next = new Set(s.selectedIds)
    ids.forEach(id => next.delete(id))
    return { selectedIds: next }
  }),

  deselectDocument: (id) =>
    set(s => {
      const next = new Set(s.selectedIds)
      next.delete(id)
      return { selectedIds: next }
    }),

  toggleSelect: (id) => {
    if (get().selectedIds.has(id)) get().deselectDocument(id)
    else get().selectDocument(id)
  },

  selectAll: () => set(s => ({ selectedIds: new Set(s.documents.map(d => d.id)) })),
  deselectAll: () => set({ selectedIds: new Set() }),
  isSelected: (id) => get().selectedIds.has(id),

  uploadFiles: async (files, folderTag) => {
    if (files.length === 0) return
    const jobsInit: UploadJob[] = files.map(f => ({ fichier: f.name, statut: 'en_attente', progress: 0 }))
    set(s => ({ uploadJobs: [...s.uploadJobs, ...jobsInit] }))

    try {
      const result = await uploadApi.uploadFiles(files, (pct) => {
        set(s => ({
          uploadJobs: s.uploadJobs.map(j =>
            jobsInit.some(ji => ji.fichier === j.fichier) ? { ...j, progress: pct } : j
          ),
        }))
      }, folderTag)

      set(s => ({
        uploadJobs: s.uploadJobs.map(j => {
          const srv = result.jobs.find(r => r.fichier === j.fichier)
          return srv ? { ...j, job_id: srv.job_id, statut: srv.statut as UploadJob['statut'] } : j
        }),
      }))

      result.jobs.forEach(job => { if (job.job_id) get().pollJobStatus(job.job_id) })
    } catch (e: unknown) {
      set(s => ({
        uploadJobs: s.uploadJobs.map(j =>
          jobsInit.some(ji => ji.fichier === j.fichier) ? { ...j, statut: 'erreur' as const } : j
        ),
        error: e instanceof Error ? e.message : 'Erreur upload',
      }))
    }
  },

  pollJobStatus: (jobId) => {
    let polls = 0
    let echecs = 0
    const abandonner = (raison: string) => set(s => ({
      uploadJobs: s.uploadJobs.map(j =>
        j.job_id === jobId ? { ...j, statut: 'erreur' as const, raison } : j
      ),
    }))
    const poll = async () => {
      if (polls++ >= ESSAIS_SUIVI_MAX) {
        // Le traitement continue peut-être côté serveur : on le dit, sans l'affirmer échoué.
        abandonner('Suivi interrompu (délai dépassé) — vérifiez dans « Tâches ».')
        return
      }
      try {
        const job = await extractApi.getJobStatus(jobId)
        echecs = 0
        set(s => ({
          uploadJobs: s.uploadJobs.map(j =>
            j.job_id === jobId ? { ...j, statut: job.statut as UploadJob['statut'] } : j
          ),
        }))
        if (job.statut === 'completed') { get().fetchDocuments(); return }
        if (job.statut === 'failed') return
        setTimeout(poll, 5000)
      } catch {
        if (++echecs >= ECHECS_SUIVI_MAX) {
          abandonner('Serveur injoignable pendant le suivi (coupure réseau ?) — vérifiez dans « Tâches ».')
          return
        }
        setTimeout(poll, 5000)
      }
    }
    setTimeout(poll, 2000)
  },

  deleteDocument: async (id) => {
    await documentsApi.delete(id)
    set(s => ({
      documents: s.documents.filter(d => d.id !== id),
      selectedIds: (() => { const n = new Set(s.selectedIds); n.delete(id); return n })(),
      total: s.total - 1,
    }))
  },

  relaunchExtraction: async (id) => {
    const result = await extractApi.relancer(id)
    if (result.job_id) get().pollJobStatus(result.job_id)
  },

  clearUploadJobs: () => set({ uploadJobs: [] }),
}))
