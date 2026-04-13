/**
 * Tests — useReport hook (logique canGenerate)
 * ==============================================
 * Teste la logique canGenerate sans rendu React
 * en manipulant directement les stores Zustand.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../api', () => ({
  generateApi: {
    startReport: vi.fn().mockResolvedValue({ job_id: 'job-test' }),
    getStreamUrl: vi.fn().mockReturnValue('http://localhost:8000/stream/job-test'),
  },
  exportApi: {
    toPdf: vi.fn().mockResolvedValue(undefined),
    toDocx: vi.fn().mockResolvedValue(undefined),
  },
  documentsApi: {
    list: vi.fn().mockResolvedValue({ documents: [], total: 0, page: 1, pages: 1 }),
    delete: vi.fn().mockResolvedValue(undefined),
  },
  extractApi: {
    getJobStatus: vi.fn().mockResolvedValue({ statut: 'completed' }),
    relancer: vi.fn().mockResolvedValue({ job_id: 'job-xyz' }),
  },
  uploadApi: {
    uploadFiles: vi.fn().mockResolvedValue({ jobs: [] }),
  },
}))

import { useReportStore } from '../../stores/reportStore'
import { useDocumentStore } from '../../stores/documentStore'

/**
 * canGenerate = selectedIds.size > 0 && prompt.trim().length > 0 && !isGenerating
 * On teste la logique pure sans passer par le hook React.
 */
function computeCanGenerate(): boolean {
  const { prompt, isGenerating } = useReportStore.getState()
  const { selectedIds } = useDocumentStore.getState()
  return selectedIds.size > 0 && prompt.trim().length > 0 && !isGenerating
}

describe('useReport — logique canGenerate', () => {
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
    useDocumentStore.setState({
      documents: [],
      selectedIds: new Set(),
      total: 0,
      page: 1,
      loading: false,
      error: null,
      uploadJobs: [],
    })
  })

  it('false si aucun document sélectionné', () => {
    useReportStore.setState({ prompt: 'Analyse les documents' })
    expect(computeCanGenerate()).toBe(false)
  })

  it('false si le prompt est vide', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1']) })
    useReportStore.setState({ prompt: '' })
    expect(computeCanGenerate()).toBe(false)
  })

  it('false si le prompt ne contient que des espaces', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1']) })
    useReportStore.setState({ prompt: '   ' })
    expect(computeCanGenerate()).toBe(false)
  })

  it('false si une génération est en cours', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1']) })
    useReportStore.setState({ prompt: 'Analyse', isGenerating: true })
    expect(computeCanGenerate()).toBe(false)
  })

  it('true quand document sélectionné + prompt non vide + pas en génération', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1', 'doc-2']) })
    useReportStore.setState({ prompt: 'Analyse ces deux documents', isGenerating: false })
    expect(computeCanGenerate()).toBe(true)
  })

  it('selectedCount reflète la taille de la sélection', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1', 'doc-2', 'doc-3']) })
    const { selectedIds } = useDocumentStore.getState()
    expect(selectedIds.size).toBe(3)
  })
})

describe('useReport — generate() appelle startGeneration avec les IDs', () => {
  it('passe les selectedIds comme tableau à startGeneration', async () => {
    useDocumentStore.setState({ selectedIds: new Set(['id-a', 'id-b']) })
    useReportStore.setState({ prompt: 'Analyse', isGenerating: false })

    const { generateApi } = await import('../../api')
    vi.mocked(generateApi.startReport).mockResolvedValueOnce({ job_id: 'job-gen' })

    const { startGeneration } = useReportStore.getState()
    const { selectedIds } = useDocumentStore.getState()
    await startGeneration([...selectedIds])

    expect(vi.mocked(generateApi.startReport)).toHaveBeenCalledWith(
      expect.objectContaining({ document_ids: expect.arrayContaining(['id-a', 'id-b']) })
    )
  })
})
