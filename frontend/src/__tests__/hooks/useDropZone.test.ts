/**
 * Tests — useDropZone hook
 * =========================
 * Vérifie la configuration react-dropzone :
 * - Formats acceptés — par EXTENSION (validator), pas par type MIME
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

/**
 * Formats acceptés — par EXTENSION, pas par type MIME.
 *
 * Ces tests interrogeaient l'option `accept` de react-dropzone (une table de types MIME).
 * Le hook ne la passe plus : il fournit un `validator` qui regarde l'extension du fichier.
 * Ils échouaient donc tous les six sur un `accept` inexistant, en décrivant un contrat que
 * plus rien ne produisait. On teste ce que le hook fait réellement.
 */
describe('useDropZone — formats acceptés', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    capturedOptions.length = 0
  })

  /** Passe un nom de fichier au validateur du hook. `null` = accepté. */
  function valider(nom: string) {
    runHook()
    const validator = capturedOptions[0]?.validator as (f: File) => { code: string; message: string } | null
    return validator(new File(['contenu'], nom))
  }

  it.each([
    'rapport.pdf', 'contrat.docx', 'budget.xlsx', 'soutenance.pptx', 'diaporama.ppsx',
    'archive.zip', 'note.odt', 'tableur.ods', 'presentation.odp',
  ])('accepte %s', (nom) => {
    expect(valider(nom)).toBeNull()
  })

  it.each(['photo.jpg', 'script.exe', 'sans-extension'])(
    'refuse %s en nommant le format en cause', (nom) => {
      const refus = valider(nom)
      expect(refus?.code).toBe('format-non-supporte')
      expect(refus?.message).toMatch(/non supporté/)
    })

  it("la casse de l'extension ne change rien", () => {
    expect(valider('RAPPORT.PDF')).toBeNull()
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
