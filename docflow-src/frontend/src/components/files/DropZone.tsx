/**
 * DropZone — Drag & drop fichiers ET dossiers
 * Utilise webkitGetAsEntry() (API native) au lieu de react-dropzone
 * car react-dropzone ne lit pas dataTransfer.items → dossiers ignorés.
 */
import { useCallback, useRef, useState } from 'react'
import { Upload, FolderOpen } from 'lucide-react'
import { clsx } from 'clsx'
import { useDocumentStore } from '../../stores/documentStore'
import { useToast } from '../common/Toast'

const ACCEPTED_EXTENSIONS = new Set(['pdf', 'docx', 'pptx', 'ppsx', 'xlsx', 'zip', 'odt', 'ods', 'odp'])

function extensionOk(file: File): boolean {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  return ACCEPTED_EXTENSIONS.has(ext)
}

async function lireDossier(entry: FileSystemDirectoryEntry): Promise<File[]> {
  const fichiers: File[] = []
  const reader = entry.createReader()
  let entrees: FileSystemEntry[]
  do {
    entrees = await new Promise((ok, ko) => reader.readEntries(ok, ko))
    for (const e of entrees) {
      if (e.isFile) {
        const f = await new Promise<File | null>(ok =>
          (e as FileSystemFileEntry).file(ok, () => ok(null))
        )
        if (f && extensionOk(f)) fichiers.push(f)
      } else if (e.isDirectory) {
        fichiers.push(...await lireDossier(e as FileSystemDirectoryEntry))
      }
    }
  } while (entrees.length > 0)
  return fichiers
}

interface Props {
  compact?: boolean
  className?: string
}

export default function DropZone({ compact = false, className }: Props) {
  const { uploadFiles } = useDocumentStore()
  const toast = useToast()
  const inputRef = useRef<HTMLInputElement>(null)
  const dragCount = useRef(0)
  const [actif, setActif] = useState(false)

  const onDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    dragCount.current++
    setActif(true)
  }
  const onDragOver = (e: React.DragEvent) => { e.preventDefault() }
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    if (--dragCount.current === 0) setActif(false)
  }

  const envoyer = useCallback(async (groupes: Map<string | undefined, File[]>) => {
    let total = 0
    for (const [tag, files] of groupes) {
      if (tag) toast.info(`Dossier "${tag}" — ${files.length} fichier(s)…`)
      else toast.info(`Upload de ${files.length} fichier(s)…`)
      await uploadFiles(files, tag)
      total += files.length
    }
    if (total > 0) toast.success(`${total} fichier(s) soumis à l'extraction`)
  }, [uploadFiles, toast])

  const onDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    dragCount.current = 0
    setActif(false)

    // dataTransfer est invalide après le premier await — tout collecter en synchrone d'abord
    type Tache =
      | { type: 'dir'; entry: FileSystemDirectoryEntry; nom: string }
      | { type: 'file'; entry: FileSystemFileEntry }
      | { type: 'plain'; file: File }

    const taches: Tache[] = []

    if (e.dataTransfer.items?.length) {
      for (const item of Array.from(e.dataTransfer.items)) {
        if (item.kind !== 'file') continue
        const entry = item.webkitGetAsEntry?.() as FileSystemEntry | null
        if (entry?.isDirectory) {
          taches.push({ type: 'dir', entry: entry as FileSystemDirectoryEntry, nom: entry.name })
        } else if (entry?.isFile) {
          taches.push({ type: 'file', entry: entry as FileSystemFileEntry })
        } else {
          const f = item.getAsFile()
          if (f) taches.push({ type: 'plain', file: f })
        }
      }
    } else {
      for (const f of Array.from(e.dataTransfer.files ?? [])) {
        taches.push({ type: 'plain', file: f })
      }
    }

    // Traitement asynchrone maintenant que dataTransfer n'est plus nécessaire
    const groupes = new Map<string | undefined, File[]>()

    for (const t of taches) {
      if (t.type === 'dir') {
        const files = await lireDossier(t.entry)
        if (files.length) groupes.set(t.nom, [...(groupes.get(t.nom) ?? []), ...files])
      } else if (t.type === 'file') {
        const file = await new Promise<File | null>(ok => t.entry.file(ok, () => ok(null)))
        if (file && extensionOk(file)) groupes.set(undefined, [...(groupes.get(undefined) ?? []), file])
      } else {
        if (extensionOk(t.file)) groupes.set(undefined, [...(groupes.get(undefined) ?? []), t.file])
      }
    }

    await envoyer(groupes)
  }, [envoyer])

  // Gestion via clic → input file classique
  const onInputChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    const groupes = new Map<string | undefined, File[]>()
    for (const f of files) {
      if (!extensionOk(f)) continue
      const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath
      const tag = rel?.includes('/') ? rel.split('/')[0] : undefined
      groupes.set(tag, [...(groupes.get(tag) ?? []), f])
    }
    await envoyer(groupes)
  }, [envoyer])

  const dragProps = { onDragEnter, onDragOver, onDragLeave, onDrop }

  if (compact) {
    return (
      <div
        {...dragProps}
        onClick={() => inputRef.current?.click()}
        className={clsx(
          'flex items-center gap-2 px-3 py-2 rounded-lg border-2 border-dashed cursor-pointer transition-colors text-sm',
          actif
            ? 'border-blue-400 bg-blue-50 text-blue-700'
            : 'border-gray-300 text-gray-500 hover:border-blue-300 hover:text-blue-600',
          className,
        )}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          aria-label="Sélectionner des fichiers"
          className="hidden"
          onChange={onInputChange}
          accept=".pdf,.docx,.pptx,.ppsx,.xlsx,.zip,.odt,.ods,.odp"
        />
        <Upload size={14} />
        <span>{actif ? 'Déposez ici…' : 'Déposer ou cliquer'}</span>
      </div>
    )
  }

  return (
    <div
      {...dragProps}
      onClick={() => inputRef.current?.click()}
      className={clsx(
        'flex flex-col items-center justify-center gap-3 p-6 rounded-xl border-2 border-dashed cursor-pointer transition-all',
        actif && 'border-blue-400 bg-blue-50 scale-[1.01]',
        !actif && 'border-gray-300 hover:border-blue-300 hover:bg-gray-50',
        className,
      )}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        aria-label="Sélectionner des fichiers"
        className="hidden"
        onChange={onInputChange}
        accept=".pdf,.docx,.pptx,.ppsx,.xlsx,.zip,.odt,.ods,.odp"
      />
      <div className={clsx('p-3 rounded-full transition-colors', actif ? 'bg-blue-100' : 'bg-gray-100')}>
        {actif
          ? <Upload size={24} className="text-blue-500" />
          : <FolderOpen size={24} className="text-gray-400" />
        }
      </div>
      <div className="text-center">
        {actif
          ? <p className="text-sm font-medium text-blue-600">Relâchez pour uploader</p>
          : <>
              <p className="text-sm font-medium text-gray-700">Glissez vos fichiers ici</p>
              <p className="text-xs text-gray-400 mt-1">ou cliquez pour parcourir</p>
            </>
        }
      </div>
      {!actif && (
        <p className="text-xs text-gray-400 text-center">PDF · DOCX · PPTX · XLSX · ZIP</p>
      )}
    </div>
  )
}
