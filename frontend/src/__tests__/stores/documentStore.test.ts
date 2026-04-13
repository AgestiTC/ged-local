/**
 * Tests — documentStore (Zustand)
 * =================================
 * Teste la sélection, la désélection, toggleSelect, selectAll, deselectAll.
 * Les appels API sont mockés avec vi.mock.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

// Mock de l'API avant d'importer le store
vi.mock('../../api', () => ({
  documentsApi: {
    list: vi.fn().mockResolvedValue({ documents: [], total: 0, page: 1, pages: 1 }),
    delete: vi.fn().mockResolvedValue(undefined),
  },
  extractApi: {
    getJobStatus: vi.fn().mockResolvedValue({ statut: 'completed' }),
    relancer: vi.fn().mockResolvedValue({ job_id: 'job-123' }),
  },
  uploadApi: {
    uploadFiles: vi.fn().mockResolvedValue({ jobs: [] }),
  },
}))

import { useDocumentStore } from '../../stores/documentStore'

const DOCS = [
  { id: 'doc-1', nom: 'rapport.pdf', chemin: '/docs/rapport.pdf', extension: 'pdf', hash_sha256: 'abc', date_import: '2026-01-01', statut: 'enriched' as const, source: 'upload' as const },
  { id: 'doc-2', nom: 'contrat.docx', chemin: '/docs/contrat.docx', extension: 'docx', hash_sha256: 'def', date_import: '2026-01-02', statut: 'enriched' as const, source: 'watch' as const },
  { id: 'doc-3', nom: 'facture.xlsx', chemin: '/docs/facture.xlsx', extension: 'xlsx', hash_sha256: 'ghi', date_import: '2026-01-03', statut: 'pending' as const, source: 'drag_drop' as const },
]

describe('documentStore — sélection', () => {
  beforeEach(() => {
    // Remettre le store à l'état initial avant chaque test
    useDocumentStore.setState({
      documents: DOCS,
      selectedIds: new Set(),
      total: 3,
      page: 1,
      loading: false,
      error: null,
      uploadJobs: [],
    })
  })

  it('sélectionner un document', () => {
    useDocumentStore.getState().selectDocument('doc-1')
    expect(useDocumentStore.getState().selectedIds.has('doc-1')).toBe(true)
    expect(useDocumentStore.getState().selectedIds.size).toBe(1)
  })

  it('désélectionner un document', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1', 'doc-2']) })
    useDocumentStore.getState().deselectDocument('doc-1')
    expect(useDocumentStore.getState().selectedIds.has('doc-1')).toBe(false)
    expect(useDocumentStore.getState().selectedIds.has('doc-2')).toBe(true)
  })

  it('toggleSelect — sélectionne si absent', () => {
    useDocumentStore.getState().toggleSelect('doc-2')
    expect(useDocumentStore.getState().selectedIds.has('doc-2')).toBe(true)
  })

  it('toggleSelect — désélectionne si présent', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-2']) })
    useDocumentStore.getState().toggleSelect('doc-2')
    expect(useDocumentStore.getState().selectedIds.has('doc-2')).toBe(false)
  })

  it('selectAll — sélectionne tous les documents chargés', () => {
    useDocumentStore.getState().selectAll()
    const ids = useDocumentStore.getState().selectedIds
    expect(ids.size).toBe(3)
    expect(ids.has('doc-1')).toBe(true)
    expect(ids.has('doc-2')).toBe(true)
    expect(ids.has('doc-3')).toBe(true)
  })

  it('deselectAll — vide la sélection', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1', 'doc-2', 'doc-3']) })
    useDocumentStore.getState().deselectAll()
    expect(useDocumentStore.getState().selectedIds.size).toBe(0)
  })

  it('isSelected retourne true/false correctement', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1']) })
    expect(useDocumentStore.getState().isSelected('doc-1')).toBe(true)
    expect(useDocumentStore.getState().isSelected('doc-2')).toBe(false)
  })
})

describe('documentStore — fetchDocuments', () => {
  beforeEach(() => {
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

  it('charge les documents depuis l\'API', async () => {
    const { documentsApi } = await import('../../api')
    vi.mocked(documentsApi.list).mockResolvedValueOnce({
      documents: DOCS,
      total: 3,
      page: 1,
      pages: 1,
    })

    await useDocumentStore.getState().fetchDocuments()

    expect(useDocumentStore.getState().documents).toHaveLength(3)
    expect(useDocumentStore.getState().total).toBe(3)
    expect(useDocumentStore.getState().loading).toBe(false)
    expect(useDocumentStore.getState().error).toBeNull()
  })

  it('passe loading à true pendant le chargement', async () => {
    const { documentsApi } = await import('../../api')
    let resolvePromise!: (v: unknown) => void
    vi.mocked(documentsApi.list).mockReturnValueOnce(
      new Promise(resolve => { resolvePromise = resolve })
    )

    const promise = useDocumentStore.getState().fetchDocuments()
    expect(useDocumentStore.getState().loading).toBe(true)

    resolvePromise({ documents: [], total: 0, page: 1, pages: 1 })
    await promise
    expect(useDocumentStore.getState().loading).toBe(false)
  })

  it('stocke l\'erreur en cas d\'échec API', async () => {
    const { documentsApi } = await import('../../api')
    vi.mocked(documentsApi.list).mockRejectedValueOnce(new Error('Réseau indisponible'))

    await useDocumentStore.getState().fetchDocuments()

    expect(useDocumentStore.getState().error).toBe('Réseau indisponible')
    expect(useDocumentStore.getState().loading).toBe(false)
  })
})

describe('documentStore — deleteDocument', () => {
  beforeEach(() => {
    useDocumentStore.setState({
      documents: DOCS,
      selectedIds: new Set(['doc-1']),
      total: 3,
      page: 1,
      loading: false,
      error: null,
      uploadJobs: [],
    })
  })

  it('retire le document de la liste et de la sélection', async () => {
    await useDocumentStore.getState().deleteDocument('doc-1')

    const state = useDocumentStore.getState()
    expect(state.documents.find(d => d.id === 'doc-1')).toBeUndefined()
    expect(state.selectedIds.has('doc-1')).toBe(false)
    expect(state.total).toBe(2)
  })

  it('laisse intacts les autres documents', async () => {
    await useDocumentStore.getState().deleteDocument('doc-1')

    const state = useDocumentStore.getState()
    expect(state.documents.find(d => d.id === 'doc-2')).toBeDefined()
    expect(state.documents.find(d => d.id === 'doc-3')).toBeDefined()
  })
})

describe('documentStore — uploadJobs', () => {
  beforeEach(() => {
    useDocumentStore.setState({
      documents: [],
      selectedIds: new Set(),
      total: 0,
      page: 1,
      loading: false,
      error: null,
      uploadJobs: [
        { fichier: 'a.pdf', statut: 'completed' },
        { fichier: 'b.pdf', statut: 'running' },
      ],
    })
  })

  it('clearUploadJobs vide la liste', () => {
    useDocumentStore.getState().clearUploadJobs()
    expect(useDocumentStore.getState().uploadJobs).toHaveLength(0)
  })
})
