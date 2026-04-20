/**
 * Hook useDropZone — drag & drop branché sur documentStore
 * Utilise react-dropzone et délègue l'upload au store.
 */
import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { useDocumentStore } from '../stores/documentStore'

const ACCEPTED_EXTENSIONS = new Set(['pdf', 'docx', 'pptx', 'ppsx', 'xlsx', 'zip', 'odt', 'ods', 'odp'])

function validateExtension(file: File) {
  const ext = (file.name ?? '').split('.').pop()?.toLowerCase() ?? ''
  if (!ACCEPTED_EXTENSIONS.has(ext)) {
    return { code: 'format-non-supporte', message: `Format .${ext} non supporté` }
  }
  return null
}

interface Options {
  /** Empêcher l'affichage du sélecteur de fichiers — utile pour les zones décoratives */
  noClick?: boolean
}

export function useDropZone(options?: Options) {
  const { uploadFiles } = useDocumentStore()

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      if (acceptedFiles.length > 0) uploadFiles(acceptedFiles)
    },
    [uploadFiles],
  )

  const dropzone = useDropzone({
    onDrop,
    validator: validateExtension,
    multiple: true,
    noClick: options?.noClick,
  })

  return dropzone
}
