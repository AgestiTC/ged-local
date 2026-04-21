/**
 * Tests — useDocuments hook
 * ==========================
 * Vérifie que le hook expose correctement les données et actions du documentStore
 * et calcule les valeurs dérivées (selectedCount).
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

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
import { useDocuments } from '../../hooks/useDocuments'

const DOCS = [
  { id: 'doc-1', nom: 'rapport.pdf', chemin: '/docs/rapport.pdf', extension: 'pdf', hash_sha256: 'aaa', date_import: '2026-01-01', statut: 'enriched' as const, source: 'upload' as const },
  { id: 'doc-2', nom: 'contrat.docx', chemin: '/docs/contrat.docx', extension: 'docx', hash_sha256: 'bbb', date_import: '2026-01-02', statut: 'enriched' as const, source: 'watch' as const },
  { id: 'doc-3', nom: 'facture.xlsx', chemin: '/docs/facture.xlsx', extension: 'xlsx', hash_sha256: 'ccc', date_import: '2026-01-03', statut: 'pending' as const, source: 'drag_drop' as const },
]

const RESET = {
  documents: DOCS,
  selectedIds: new Set<string>(),
  total: 3,
  page: 1,
  loading: false,
  error: null,
  uploadJobs: [],
}

describe('useDocuments — valeurs exposées', () => {
  beforeEach(() => {
    useDocumentStore.setState(RESET)
    vi.clearAllMocks()
  })

  it('expose documents depuis le store', () => {
    const hook = useDocuments()
    expect(hook.documents).toHaveLength(3)
    expect(hook.documents[0].nom).toBe('rapport.pdf')
  })

  it('expose total, page, loading, error', () => {
    const hook = useDocuments()
    expect(hook.total).toBe(3)
    expect(hook.page).toBe(1)
    expect(hook.loading).toBe(false)
    expect(hook.error).toBeNull()
  })

  it('selectedCount vaut 0 initialement', () => {
    const hook = useDocuments()
    expect(hook.selectedCount).toBe(0)
  })

  it('selectedCount reflète le nombre de documents sélectionnés', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1', 'doc-2']) })
    const hook = useDocuments()
    expect(hook.selectedCount).toBe(2)
  })

  it('expose selectedIds comme un Set', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-3']) })
    const hook = useDocuments()
    expect(hook.selectedIds).toBeInstanceOf(Set)
    expect(hook.selectedIds.has('doc-3')).toBe(true)
  })

  it('expose uploadJobs', () => {
    const hook = useDocuments()
    expect(Array.isArray(hook.uploadJobs)).toBe(true)
  })
})

describe('useDocuments — actions', () => {
  beforeEach(() => {
    useDocumentStore.setState(RESET)
    vi.clearAllMocks()
  })

  it('expose fetchDocuments comme fonction', () => {
    const hook = useDocuments()
    expect(typeof hook.fetchDocuments).toBe('function')
  })

  it('expose toggleSelect, selectAll, deselectAll, isSelected', () => {
    const hook = useDocuments()
    expect(typeof hook.toggleSelect).toBe('function')
    expect(typeof hook.selectAll).toBe('function')
    expect(typeof hook.deselectAll).toBe('function')
    expect(typeof hook.isSelected).toBe('function')
  })

  it('expose selectDocument, deselectDocument', () => {
    const hook = useDocuments()
    expect(typeof hook.selectDocument).toBe('function')
    expect(typeof hook.deselectDocument).toBe('function')
  })

  it('expose uploadFiles, deleteDocument, relaunchExtraction', () => {
    const hook = useDocuments()
    expect(typeof hook.uploadFiles).toBe('function')
    expect(typeof hook.deleteDocument).toBe('function')
    expect(typeof hook.relaunchExtraction).toBe('function')
  })

  it('expose clearUploadJobs', () => {
    const hook = useDocuments()
    expect(typeof hook.clearUploadJobs).toBe('function')
  })

  it('toggleSelect ajoute un ID à la sélection', () => {
    useDocuments().toggleSelect('doc-1')
    expect(useDocumentStore.getState().selectedIds.has('doc-1')).toBe(true)
  })

  it('selectAll sélectionne tous les documents', () => {
    useDocuments().selectAll()
    const selected = useDocumentStore.getState().selectedIds
    expect(selected.size).toBe(3)
  })

  it('deselectAll vide la sélection', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1', 'doc-2']) })
    useDocuments().deselectAll()
    expect(useDocumentStore.getState().selectedIds.size).toBe(0)
  })

  it('isSelected retourne true pour un doc sélectionné', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-2']) })
    expect(useDocuments().isSelected('doc-2')).toBe(true)
    expect(useDocuments().isSelected('doc-3')).toBe(false)
  })

  it('selectDocument ajoute le doc à la sélection sans retirer les autres', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1']) })
    useDocuments().selectDocument('doc-2')
    const selected = useDocumentStore.getState().selectedIds
    expect(selected.has('doc-1')).toBe(true)
    expect(selected.has('doc-2')).toBe(true)
  })

  it('deselectDocument retire uniquement le doc ciblé', () => {
    useDocumentStore.setState({ selectedIds: new Set(['doc-1', 'doc-2']) })
    useDocuments().deselectDocument('doc-1')
    const selected = useDocumentStore.getState().selectedIds
    expect(selected.has('doc-1')).toBe(false)
    expect(selected.has('doc-2')).toBe(true)
  })
})
