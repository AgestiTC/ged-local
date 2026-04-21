/**
 * Tests — reportStore (Zustand)
 * ================================
 * Teste la configuration du rapport, le streaming SSE,
 * l'historique, et l'annulation.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../api', () => ({
  generateApi: {
    startReport: vi.fn().mockResolvedValue({ job_id: 'job-abc' }),
    getStreamUrl: vi.fn().mockReturnValue('http://localhost:8000/api/generate/stream/job-abc'),
  },
  exportApi: {
    toPdf: vi.fn().mockResolvedValue(undefined),
    toDocx: vi.fn().mockResolvedValue(undefined),
  },
}))

import { useReportStore } from '../../stores/reportStore'

describe('reportStore — configuration', () => {
  beforeEach(() => {
    useReportStore.setState({
      prompt: '',
      model: 'mixtral:latest',
      outputMode: 'rapport_libre',
      isGenerating: false,
      jobId: null,
      rapportEnCours: '',
      rapportFinal: '',
      error: null,
      historique: [],
    })
  })

  it('setPrompt met à jour le prompt', () => {
    useReportStore.getState().setPrompt('Analyse ce document')
    expect(useReportStore.getState().prompt).toBe('Analyse ce document')
  })

  it('setModel met à jour le modèle', () => {
    useReportStore.getState().setModel('mistral:latest')
    expect(useReportStore.getState().model).toBe('mistral:latest')
  })

  it('setOutputMode met à jour le mode', () => {
    useReportStore.getState().setOutputMode('classement')
    expect(useReportStore.getState().outputMode).toBe('classement')
  })
})

describe('reportStore — appendChunk / finishGeneration', () => {
  beforeEach(() => {
    useReportStore.setState({
      prompt: 'Analyse',
      model: 'mixtral:latest',
      outputMode: 'rapport_libre',
      isGenerating: true,
      jobId: 'job-abc',
      rapportEnCours: '',
      rapportFinal: '',
      error: null,
      historique: [],
    })
  })

  it('appendChunk accumule les chunks', () => {
    useReportStore.getState().appendChunk('Bonjour ')
    useReportStore.getState().appendChunk('le monde')
    expect(useReportStore.getState().rapportEnCours).toBe('Bonjour le monde')
  })

  it('finishGeneration termine la génération et ajoute à l\'historique', () => {
    useReportStore.getState().appendChunk('Contenu du rapport.')
    useReportStore.getState().finishGeneration('Contenu du rapport.')

    const state = useReportStore.getState()
    expect(state.isGenerating).toBe(false)
    expect(state.rapportFinal).toBe('Contenu du rapport.')
    expect(state.historique).toHaveLength(1)
    expect(state.historique[0].rapport).toBe('Contenu du rapport.')
    expect(state.historique[0].prompt).toBe('Analyse')
  })

  it('l\'historique est limité à 20 entrées', () => {
    // Pré-remplir avec 20 entrées
    const existing = Array.from({ length: 20 }, (_, i) => ({
      id: `id-${i}`,
      prompt: `prompt ${i}`,
      rapport: `rapport ${i}`,
      model: 'mixtral:latest',
      created_at: '2026-01-01T00:00:00Z',
      nb_documents: 0,
    }))
    useReportStore.setState({ historique: existing })

    useReportStore.getState().finishGeneration('Nouveau rapport')
    expect(useReportStore.getState().historique).toHaveLength(20)
    expect(useReportStore.getState().historique[0].rapport).toBe('Nouveau rapport')
  })
})

describe('reportStore — cancelGeneration / resetRapport', () => {
  beforeEach(() => {
    useReportStore.setState({
      prompt: '',
      model: 'mixtral:latest',
      outputMode: 'rapport_libre',
      isGenerating: true,
      jobId: 'job-abc',
      rapportEnCours: 'partiel...',
      rapportFinal: '',
      error: null,
      historique: [],
    })
  })

  it('cancelGeneration arrête la génération avec un message d\'erreur', () => {
    useReportStore.getState().cancelGeneration()
    expect(useReportStore.getState().isGenerating).toBe(false)
    expect(useReportStore.getState().error).toBe('Génération annulée')
  })

  it('resetRapport nettoie le rapport et l\'erreur', () => {
    useReportStore.setState({ error: 'Connexion perdue', rapportFinal: 'ancien', jobId: 'old-job' })
    useReportStore.getState().resetRapport()

    const state = useReportStore.getState()
    expect(state.rapportEnCours).toBe('')
    expect(state.rapportFinal).toBe('')
    expect(state.error).toBeNull()
    expect(state.jobId).toBeNull()
  })
})

describe('reportStore — startGeneration', () => {
  beforeEach(() => {
    useReportStore.setState({
      prompt: 'Analyse les documents',
      model: 'mixtral:latest',
      outputMode: 'rapport_libre',
      isGenerating: false,
      jobId: null,
      rapportEnCours: '',
      rapportFinal: '',
      error: null,
      historique: [],
    })
  })

  it('ne démarre pas si le prompt est vide', async () => {
    useReportStore.setState({ prompt: '   ' })
    await useReportStore.getState().startGeneration(['doc-1'])
    expect(useReportStore.getState().isGenerating).toBe(false)
  })

  it('passe isGenerating à true et définit jobId', async () => {
    const { generateApi } = await import('../../api')
    // La résolution sera bloquée pour vérifier l'état intermédiaire
    vi.mocked(generateApi.startReport).mockResolvedValueOnce({ job_id: 'job-xyz' })

    const promise = useReportStore.getState().startGeneration(['doc-1', 'doc-2'])
    // isGenerating devrait être true immédiatement (avant que la promesse résolve)
    expect(useReportStore.getState().isGenerating).toBe(true)
    await promise
    expect(useReportStore.getState().jobId).toBe('job-xyz')
  })

  it('stocke l\'erreur si l\'API échoue', async () => {
    const { generateApi } = await import('../../api')
    vi.mocked(generateApi.startReport).mockRejectedValueOnce(new Error('Ollama indisponible'))

    await useReportStore.getState().startGeneration(['doc-1'])

    const state = useReportStore.getState()
    expect(state.isGenerating).toBe(false)
    expect(state.error).toBe('Ollama indisponible')
  })
})
