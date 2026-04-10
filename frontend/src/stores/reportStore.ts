/**
 * Store rapport — Zustand
 * TODO Phase 2
 */
import { create } from 'zustand'
import type { OutputMode } from '../types'

interface ReportStore {
  prompt: string
  model: string
  outputMode: OutputMode
  result: string
  isGenerating: boolean
  setPrompt: (prompt: string) => void
  setModel: (model: string) => void
  setOutputMode: (mode: OutputMode) => void
  setResult: (result: string) => void
  setGenerating: (generating: boolean) => void
}

export const useReportStore = create<ReportStore>((set) => ({
  prompt: '',
  model: 'mixtral:latest',
  outputMode: 'rapport_libre',
  result: '',
  isGenerating: false,
  setPrompt: (prompt) => set({ prompt }),
  setModel: (model) => set({ model }),
  setOutputMode: (outputMode) => set({ outputMode }),
  setResult: (result) => set({ result }),
  setGenerating: (isGenerating) => set({ isGenerating }),
}))
