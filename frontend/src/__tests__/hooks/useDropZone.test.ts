/**
 * Tests — useDropZone hook
 * =========================
 * Vérifie la configuration react-dropzone :
 * - Types MIME acceptés (PDF, DOCX, XLSX, PPTX, ZIP, ODF)
 * - Délégation de l'upload au documentStore via uploadFiles
 * - Option noClick
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

// Mock react-dropzone — on capture les options passées à useDropzone
const capturedOptions: Record<string, unknown>[] = []
vi.mock('react-dropzone', () => ({
  useDropzone: vi.fn((opts) => {
    capturedOptions.push(opts)
    return {
      getRootProps: vi.fn(() => ({})),
      getInputProps: vi.fn(() => ({})),
      isDragActive: false,
      acceptedFiles: [],
      open: vi.fn(),
    }
  }),
}))

// Mock du documentStore
const mockUploadFiles = vi.fn()
vi.mock('../../stores/documentStore', () => ({
  useDocumentStore: vi.fn(() => ({
    uploadFiles: mockUploadFiles,
  })),
}))

import { useDropZone } from '../../hooks/useDropZone'

// Exécuter le hook (pas besoin de renderHook — c'est un hook pur sans DOM)
function runHook(options?: Parameters<typeof useDropZone>[0]) {
  capturedOptions.length = 0
  return useDropZone(options)
}

describe('useDropZone — types MIME acceptés', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    capturedOptions.length = 0
  })

  it('accepte les PDF', () => {
    runHook()
    const accept = capturedOptions[0]?.accept as Record<string, string[]>
    expect(accept).toHaveProperty('application/pdf')
    expect(accept['application/pdf']).toContain('.pdf')
  })

  it('accepte les DOCX', () => {
    runHook()
    const accept = capturedOptions[0]?.accept as Record<string, string[]>
    const docxMime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    expect(accept).toHaveProperty(docxMime)
    expect(accept[docxMime]).toContain('.docx')
  })

  it('accepte les XLSX', () => {
    runHook()
    const accept = capturedOptions[0]?.accept as Record<string, string[]>
    const xlsxMime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    expect(accept).toHaveProperty(xlsxMime)
    expect(accept[xlsxMime]).toContain('.xlsx')
  })

  it('accepte les PPTX et PPSX', () => {
    runHook()
    const accept = capturedOptions[0]?.accept as Record<string, string[]>
    const pptxMime = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    expect(accept).toHaveProperty(pptxMime)
    expect(accept[pptxMime]).toContain('.pptx')
    expect(accept[pptxMime]).toContain('.ppsx')
  })

  it('accepte les ZIP', () => {
    runHook()
    const accept = capturedOptions[0]?.accept as Record<string, string[]>
    expect(accept).toHaveProperty('application/zip')
    expect(accept['application/zip']).toContain('.zip')
  })

  it('accepte les formats ODF (ODT, ODS, ODP)', () => {
    runHook()
    const accept = capturedOptions[0]?.accept as Record<string, string[]>
    expect(accept).toHaveProperty('application/vnd.oasis.opendocument.text')
    expect(accept).toHaveProperty('application/vnd.oasis.opendocument.spreadsheet')
    expect(accept).toHaveProperty('application/vnd.oasis.opendocument.presentation')
  })

  it('accepte multiple fichiers (multiple: true)', () => {
    runHook()
    expect(capturedOptions[0]?.multiple).toBe(true)
  })
})

describe('useDropZone — délégation upload', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    capturedOptions.length = 0
  })

  it('appelle uploadFiles avec les fichiers déposés', () => {
    runHook()
    const onDrop = capturedOptions[0]?.onDrop as (files: File[]) => void
    const fichiers = [new File(['contenu'], 'doc.pdf', { type: 'application/pdf' })]

    onDrop(fichiers)

    expect(mockUploadFiles).toHaveBeenCalledOnce()
    expect(mockUploadFiles).toHaveBeenCalledWith(fichiers)
  })

  it('n\'appelle pas uploadFiles si aucun fichier accepté', () => {
    runHook()
    const onDrop = capturedOptions[0]?.onDrop as (files: File[]) => void

    onDrop([])

    expect(mockUploadFiles).not.toHaveBeenCalled()
  })

  it('transmet tous les fichiers d\'un dépôt multi-fichiers', () => {
    runHook()
    const onDrop = capturedOptions[0]?.onDrop as (files: File[]) => void
    const fichiers = [
      new File(['a'], 'doc1.pdf', { type: 'application/pdf' }),
      new File(['b'], 'doc2.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }),
      new File(['c'], 'archive.zip', { type: 'application/zip' }),
    ]

    onDrop(fichiers)

    expect(mockUploadFiles).toHaveBeenCalledWith(fichiers)
  })
})

describe('useDropZone — option noClick', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    capturedOptions.length = 0
  })

  it('noClick est false par défaut', () => {
    runHook()
    // Sans option, noClick doit être undefined ou false (pas true)
    expect(capturedOptions[0]?.noClick).not.toBe(true)
  })

  it('noClick=true est transmis à useDropzone', () => {
    runHook({ noClick: true })
    expect(capturedOptions[0]?.noClick).toBe(true)
  })

  it('noClick=false est transmis à useDropzone', () => {
    runHook({ noClick: false })
    expect(capturedOptions[0]?.noClick).toBe(false)
  })
})

describe('useDropZone — valeur retournée', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    capturedOptions.length = 0
  })

  it('retourne getRootProps, getInputProps, isDragActive', () => {
    const result = runHook()
    expect(typeof result.getRootProps).toBe('function')
    expect(typeof result.getInputProps).toBe('function')
    expect(typeof result.isDragActive).toBe('boolean')
  })

  it('retourne open (pour déclencher le sélecteur programmatiquement)', () => {
    const result = runHook()
    expect(typeof result.open).toBe('function')
  })
})
