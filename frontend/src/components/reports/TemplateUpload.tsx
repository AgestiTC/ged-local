/**
 * TemplateUpload — Upload et sélection de templates DOCX
 * Affiche les templates existants + zone d'upload.
 */
import { useEffect, useState } from 'react'
import { Upload, FileText, Trash2, CheckSquare, Square } from 'lucide-react'
import { useDropzone } from 'react-dropzone'
import { clsx } from 'clsx'
import { templatesApi } from '../../api'
import type { Template } from '../../types'
import { useToast } from '../common/Toast'
import LoadingSpinner from '../common/LoadingSpinner'

interface Props {
  selectedTemplateId?: string
  onSelect: (templateId: string | undefined) => void
}

export default function TemplateUpload({ selectedTemplateId, onSelect }: Props) {
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const toast = useToast()

  useEffect(() => {
    templatesApi.list()
      .then(d => setTemplates(d.templates))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'] },
    multiple: false,
    onDrop: async ([file]) => {
      if (!file) return
      setUploading(true)
      try {
        const t = await templatesApi.upload(file)
        setTemplates(prev => [...prev, t])
        toast.success(`Template "${t.nom}" uploadé — ${(t.champs ?? []).length} champ(s) détecté(s)`)
      } catch {
        toast.error('Erreur upload template')
      } finally {
        setUploading(false)
      }
    },
  })

  const supprimer = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await templatesApi.delete(id)
      setTemplates(prev => prev.filter(t => t.id !== id))
      if (selectedTemplateId === id) onSelect(undefined)
      toast.success('Template supprimé')
    } catch {
      toast.error('Erreur suppression template')
    }
  }

  return (
    <div className="space-y-3">
      {/* Zone upload */}
      <div
        {...getRootProps()}
        className={clsx(
          'flex items-center gap-2 px-3 py-2.5 rounded-lg border-2 border-dashed cursor-pointer transition-colors text-xs',
          isDragActive ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-gray-300 text-gray-400 hover:border-blue-300',
        )}
      >
        <input {...getInputProps()} />
        {uploading ? <LoadingSpinner size={14} /> : <Upload size={14} />}
        <span>{isDragActive ? 'Déposez le template…' : 'Déposer un template DOCX ou cliquer'}</span>
      </div>

      {/* Liste des templates */}
      {loading && <LoadingSpinner label="Chargement…" size={14} />}
      {!loading && templates.length === 0 && (
        <p className="text-xs text-gray-400 text-center py-2">Aucun template disponible</p>
      )}
      <div className="space-y-1">
        {templates.map(t => {
          const selected = t.id === selectedTemplateId
          return (
            <div
              key={t.id}
              onClick={() => onSelect(selected ? undefined : t.id)}
              className={clsx(
                'flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer group transition-colors text-xs border',
                selected ? 'border-blue-300 bg-blue-50' : 'border-transparent hover:bg-gray-50',
              )}
            >
              {selected ? <CheckSquare size={13} className="text-blue-600 shrink-0" /> : <Square size={13} className="text-gray-300 shrink-0" />}
              <FileText size={13} className="text-gray-400 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="font-medium text-gray-700 truncate">{t.nom}</p>
                {t.champs && t.champs.length > 0 && (
                  <p className="text-gray-400">{t.champs.length} champ(s) : {t.champs.slice(0, 3).map(c => `{{${c.nom}}}`).join(', ')}{t.champs.length > 3 ? '…' : ''}</p>
                )}
              </div>
              <button
                onClick={e => supprimer(t.id, e)}
                className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600 transition-opacity"
              >
                <Trash2 size={12} />
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
