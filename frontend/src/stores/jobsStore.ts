/**
 * Store Jobs — Zustand
 * ====================
 * Cache partagé des jobs récents (tâches durables) alimenté par le polling du widget
 * « Tâches en cours » (Header). Permet à n'importe quel composant de lire l'état global.
 */
import { create } from 'zustand'
import type { JobInfo } from '../api'

interface JobsState {
  jobs: JobInfo[]
  setJobs: (jobs: JobInfo[]) => void
}

export const useJobsStore = create<JobsState>((set) => ({
  jobs: [],
  setJobs: (jobs) => set({ jobs }),
}))

/** Vrai si le job est encore en attente ou en cours. */
export const jobActif = (statut: string) => statut === 'pending' || statut === 'running'
