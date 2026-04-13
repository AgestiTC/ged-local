/**
 * Hook useDropZone — drag & drop branché sur documentStore
 * Utilise react-dropzone et délègue l'upload au store.
 */
import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { useDocumentStore } from '../stores/documentStore'

const ACCEPTED_TYPES = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx', '.ppsx'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/zip': ['.zip'],
  'application/vnd.oasis.opendocument.text': ['.odt'],
  'application/vnd.oasis.opendocument.spreadsheet': ['.ods'],
  'application/vnd.oasis.opendocument.presentation': ['.odp'],
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
    accept: ACCEPTED_TYPES,
    multiple: true,
    noClick: options?.noClick,
  })

  return dropzone
}
