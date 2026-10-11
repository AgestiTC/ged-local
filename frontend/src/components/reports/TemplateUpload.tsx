/**
 * TemplateUpload — Upload et sélection de templates DOCX
 * Affiche les templates existants + zone d'upload.
 */
import { useEffect, useState } from 'react'
import { Upload, FileText, Trash2, CheckSquare, Square, Download, Eye, Loader2 } from 'lucide-react'
import { useDropzone } from 'react-dropzone'
import { clsx } from 'clsx'
import { templatesApi, type TemplateApercu } from '../../api'
import type { Template } from '../../types'
import { useToast } from '../common/Toast'
import LoadingSpinner from '../common/LoadingSpinner'

interface Props {
  selectedTemplateId?: string
  onSelect: (templateId: string | undefined) => void
  /** Modèle choisi = grille d'analyse des offres : proposer de passer en Tableau comparatif. */
  onUtiliserGrille?: () => void
}

/** Grille d'analyse (critères en lignes, un bloc par candidat) : relève du Tableau comparatif. */
export const estGrille = (t?: Template) =>
  !!t && ((t.description ?? '').startsWith("Grille d'analyse") || (t.champs ?? []).some(c => c.type === 'critere'))

export default function TemplateUpload({ selectedTemplateId, onSelect, onUtiliserGrille }: Props) {
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  // Aperçu « ce que Matothèque reconnaît » d'un classeur : ouvert d'office pour le modèle Excel
  // choisi — une grille mal reconnue se voit AVANT de lancer (11/10/2026 : six refus d'affilée).
  const [apercuOuvert, setApercuOuvert] = useState<string | null>(null)
  const [apercus, setApercus] = useState<Record<string, TemplateApercu | 'chargement' | 'erreur'>>({})
  const toast = useToast()

  useEffect(() => {
    templatesApi.list()
      .then(d => setTemplates(d.templates))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const chargerApercu = (id: string) => {
    setApercuOuvert(id)
    if (apercus[id] && apercus[id] !== 'erreur') return
    setApercus(prev => ({ ...prev, [id]: 'chargement' }))
    templatesApi.apercu(id)
      .then(a => setApercus(prev => ({ ...prev, [id]: a })))
      .catch(() => setApercus(prev => ({ ...prev, [id]: 'erreur' })))
  }

  const estExcel = (t?: Template) => !!t && t.type === 'xlsx'

  useEffect(() => {
    const t = templates.find(x => x.id === selectedTemplateId)
    if (t && estExcel(t)) chargerApercu(t.id)   // à chaque sélection (ou liste rechargée) seulement
  }, [selectedTemplateId, templates])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: {
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
    },
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
        <span>{isDragActive ? 'Déposez le template…' : 'Déposer un template DOCX / XLSX ou cliquer'}</span>
      </div>

      {/* Liste des templates */}
      {loading && <LoadingSpinner label="Chargement…" size={14} />}
      {!loading && templates.length === 0 && (
        <p className="text-xs text-gray-400 text-center py-2">Aucun template disponible</p>
      )}
      <div className="space-y-1">
        {templates.map(t => {
          const selected = t.id === selectedTemplateId
          const apercu = apercus[t.id]
          return (
            <div key={t.id}>
            <div
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
              {estExcel(t) && (
                <button
                  type="button"
                  onClick={e => { e.stopPropagation(); apercuOuvert === t.id ? setApercuOuvert(null) : chargerApercu(t.id) }}
                  title="Aperçu : ce que Matothèque reconnaît dans ce classeur"
                  className="text-gray-400 hover:text-blue-600 transition-colors"
                >
                  <Eye size={13} />
                </button>
              )}
              <a
                href={templatesApi.fichierUrl(t.id)}
                download
                onClick={e => e.stopPropagation()}
                title="Télécharger le modèle (à ouvrir dans Excel / Word)"
                className="text-gray-400 hover:text-blue-600 transition-colors"
              >
                <Download size={13} />
              </a>
              <button
                onClick={e => supprimer(t.id, e)}
                title="Supprimer le modèle"
                className="opacity-100 md:opacity-0 md:group-hover:opacity-100 text-red-400 hover:text-red-600 transition-opacity"
              >
                <Trash2 size={12} />
              </button>
            </div>
            {apercuOuvert === t.id && apercu && (
              <div className="ml-6 mt-1 mb-2 rounded-lg border border-gray-200 bg-white p-2.5 text-xs space-y-1.5">
                {apercu === 'chargement' ? (
                  <p className="flex items-center gap-1.5 text-gray-400">
                    <Loader2 size={12} className="animate-spin" /> Lecture du classeur…
                  </p>
                ) : apercu === 'erreur' ? (
                  <p className="text-red-600">Aperçu impossible (fichier introuvable sur le serveur ?)</p>
                ) : (
                  <>
                    <p className={clsx(apercu.type === 'inconnu' ? 'text-red-700' : 'text-gray-600')}>
                      {apercu.message}
                    </p>
                    {apercu.criteres.length > 0 && (
                      <ol className="list-decimal pl-5 text-gray-700 space-y-0.5 max-h-48 overflow-y-auto">
                        {apercu.criteres.map((c, i) => (
                          <li key={i}>
                            {c.nom}
                            {c.points != null && <span className="text-gray-400"> — {c.points} pts</span>}
                          </li>
                        ))}
                      </ol>
                    )}
                  </>
                )}
              </div>
            )}
            </div>
          )
        })}
      </div>

      {onUtiliserGrille && estGrille(templates.find(t => t.id === selectedTemplateId)) && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 space-y-2">
          <p>
            <strong>C'est une grille d'analyse des offres.</strong> Ce mode remplit des champs isolés ;
            une grille se remplit candidat par candidat, critère par critère — c'est le
            <strong> Tableau comparatif</strong>. Les documents cochés y seront répartis par dossier de candidat.
          </p>
          <button
            type="button"
            onClick={onUtiliserGrille}
            className="w-full py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold"
          >
            Passer en Tableau comparatif avec cette grille
          </button>
        </div>
      )}
    </div>
  )
}
