/**
 * DropZone — Zone de drag & drop pour fichiers, dossiers, ZIP
 * Accepte : PDF, DOCX, PPTX, PPSX, XLSX, ZIP (+ dossiers via webkitdirectory)
 */
import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FolderOpen } from 'lucide-react'
import { clsx } from 'clsx'
import { useDocumentStore } from '../../stores/documentStore'
import { useToast } from '../common/Toast'

const ACCEPTED_EXTENSIONS = new Set(['pdf', 'docx', 'pptx', 'ppsx', 'xlsx', 'zip', 'odt', 'ods', 'odp'])

function validateExtension(file: File) {
  const ext = (file.name ?? '').split('.').pop()?.toLowerCase() ?? ''
  if (!ACCEPTED_EXTENSIONS.has(ext)) {
    return { code: 'format-non-supporte', message: `Format .${ext} non supporté` }
  }
  return null
}

interface Props {
  compact?: boolean // Affichage compact (inline) ou plein (zone large)
  className?: string
}

export default function DropZone({ compact = false, className }: Props) {
  const { uploadFiles } = useDocumentStore()
  const toast = useToast()

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return
    toast.info(`Upload de ${acceptedFiles.length} fichier(s)…`)
    await uploadFiles(acceptedFiles)
    toast.success(`${acceptedFiles.length} fichier(s) soumis à l'extraction`)
  }, [uploadFiles, toast])

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    validator: validateExtension,
    multiple: true,
  })

  if (compact) {
    return (
      <div
        {...getRootProps()}
        className={clsx(
          'flex items-center gap-2 px-3 py-2 rounded-lg border-2 border-dashed cursor-pointer transition-colors text-sm',
          isDragActive ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-gray-300 text-gray-500 hover:border-blue-300 hover:text-blue-600',
          isDragReject && 'border-red-400 bg-red-50 text-red-600',
          className,
        )}
      >
        <input {...getInputProps()} />
        <Upload size={14} />
        <span>{isDragActive ? 'Déposez ici…' : 'Déposer ou cliquer'}</span>
      </div>
    )
  }

  return (
    <div
      {...getRootProps()}
      className={clsx(
        'flex flex-col items-center justify-center gap-3 p-6 rounded-xl border-2 border-dashed cursor-pointer transition-all',
        isDragActive && !isDragReject && 'border-blue-400 bg-blue-50 scale-[1.01]',
        isDragReject && 'border-red-400 bg-red-50',
        !isDragActive && !isDragReject && 'border-gray-300 hover:border-blue-300 hover:bg-gray-50',
        className,
      )}
    >
      <input {...getInputProps()} />
      <div className={clsx(
        'p-3 rounded-full transition-colors',
        isDragActive ? 'bg-blue-100' : 'bg-gray-100',
      )}>
        {isDragActive ? (
          <Upload size={24} className="text-blue-500" />
        ) : (
          <FolderOpen size={24} className="text-gray-400" />
        )}
      </div>
      <div className="text-center">
        {isDragActive && !isDragReject && (
          <p className="text-sm font-medium text-blue-600">Relâchez pour uploader</p>
        )}
        {isDragReject && (
          <p className="text-sm font-medium text-red-600">Format non supporté</p>
        )}
        {!isDragActive && (
          <>
            <p className="text-sm font-medium text-gray-700">Glissez vos fichiers ici</p>
            <p className="text-xs text-gray-400 mt-1">ou cliquez pour parcourir</p>
          </>
        )}
      </div>
      {!isDragActive && (
        <p className="text-xs text-gray-400 text-center">
          PDF · DOCX · PPTX · XLSX · ZIP
        </p>
      )}
    </div>
  )
}
