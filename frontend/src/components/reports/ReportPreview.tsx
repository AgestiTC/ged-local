/**
 * ReportPreview — Prévisualisation du rapport généré (Markdown rendu)
 * Affiche le contenu streamé en temps réel + boutons d'export.
 */
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { BookOpen, Copy, Download, FileText, RotateCcw, RefreshCw } from 'lucide-react'
import { clsx } from 'clsx'
import { useReportStore } from '../../stores/reportStore'
import { useDocumentStore } from '../../stores/documentStore'
import LoadingSpinner from '../common/LoadingSpinner'
import PublishBookStackModal from '../common/PublishBookStackModal'
import { useToast } from '../common/Toast'

/** Déduit un titre par défaut depuis le 1er titre Markdown (ou une valeur générique). */
function titreParDefaut(markdown: string): string {
  const ligne = markdown.split('\n').find(l => l.trim().startsWith('#'))
  return ligne ? ligne.replace(/^#+\s*/, '').trim().slice(0, 120) : 'Nouveau tuto'
}

export default function ReportPreview() {
  const { rapportEnCours, rapportFinal, isGenerating, error, resetRapport, exportPdf, exportDocx, startGeneration, outputMode, prompt } = useReportStore()
  const { selectedIds } = useDocumentStore()
  const MODE_LABEL: Record<string, string> = {
    rapport_libre: 'Rapport libre', remplir_template: 'Remplir un template',
    classement: 'Classement / tri', comparatif: 'Comparatif',
  }
  const [mode, setMode] = useState<'preview' | 'source'>('preview')
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null)
  const [showPublish, setShowPublish] = useState(false)
  const toast = useToast()

  const contenu = rapportEnCours || rapportFinal
  const vide = !contenu && !isGenerating

  const copier = async () => {
    await navigator.clipboard.writeText(contenu)
    toast.success('Copié dans le presse-papier')
  }

  const handleExport = async (type: 'pdf' | 'docx') => {
    setExporting(type)
    try {
      if (type === 'pdf') await exportPdf()
      else await exportDocx()
      toast.success(`Export ${type.toUpperCase()} téléchargé`)
    } catch {
      toast.error(`Erreur export ${type.toUpperCase()}`)
    } finally {
      setExporting(null)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Barre d'outils */}
      <div className="flex items-center justify-between mb-2 shrink-0">
        <div className="flex rounded-md border border-gray-200 overflow-hidden text-xs">
          {(['preview', 'source'] as const).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={clsx('px-2.5 py-1', mode === m ? 'bg-gray-100 font-medium text-gray-800' : 'text-gray-500 hover:text-gray-700')}
            >
              {m === 'preview' ? 'Aperçu' : 'Source'}
            </button>
          ))}
        </div>

        {contenu && (
          <div className="flex items-center gap-1">
            <button onClick={copier} title="Copier" className="p-1.5 text-gray-400 hover:text-gray-700 rounded-md hover:bg-gray-100">
              <Copy size={13} />
            </button>
            <button
              onClick={() => handleExport('pdf')}
              disabled={!!exporting}
              title="Exporter PDF"
              className="flex items-center gap-1 text-xs px-2 py-1.5 text-gray-600 hover:bg-gray-100 rounded-md disabled:opacity-40"
            >
              {exporting === 'pdf' ? <LoadingSpinner size={12} /> : <Download size={12} />}
              PDF
            </button>
            <button
              onClick={() => handleExport('docx')}
              disabled={!!exporting}
              title="Exporter DOCX"
              className="flex items-center gap-1 text-xs px-2 py-1.5 text-gray-600 hover:bg-gray-100 rounded-md disabled:opacity-40"
            >
              {exporting === 'docx' ? <LoadingSpinner size={12} /> : <FileText size={12} />}
              DOCX
            </button>
            <button
              onClick={() => setShowPublish(true)}
              disabled={isGenerating || !contenu}
              title="Publier comme tuto sur le wiki BookStack"
              className="flex items-center gap-1 text-xs px-2 py-1.5 text-purple-600 hover:bg-purple-50 rounded-md disabled:opacity-40"
            >
              <BookOpen size={12} />
              Wiki
            </button>
            <button
              onClick={() => startGeneration([...selectedIds])}
              disabled={isGenerating || selectedIds.size === 0}
              title={selectedIds.size === 0 ? 'Sélectionnez des documents pour régénérer' : 'Régénérer avec la sélection et le prompt actuels'}
              className="flex items-center gap-1 text-xs px-2 py-1.5 text-gray-600 hover:bg-gray-100 rounded-md disabled:opacity-40"
            >
              <RefreshCw size={12} className={isGenerating ? 'animate-spin' : ''} />
              Régénérer
            </button>
            <button onClick={resetRapport} title="Effacer" className="p-1.5 text-gray-400 hover:text-gray-700 rounded-md hover:bg-gray-100">
              <RotateCcw size={13} />
            </button>
          </div>
        )}
      </div>

      {/* Corps */}
      <div className="flex-1 overflow-y-auto min-h-0 rounded-lg border border-gray-200 bg-white">
        {vide && !error && (
          <div className="h-full p-5 flex flex-col gap-4">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Votre rapport</p>
            <ul className="space-y-2 text-sm text-gray-600">
              <li className="flex items-center gap-2">
                <span>{selectedIds.size > 0 ? '✅' : '⬜'}</span>
                Documents : <strong>{selectedIds.size}</strong> sélectionné{selectedIds.size > 1 ? 's' : ''}
              </li>
              <li className="flex items-center gap-2">
                <span>📄</span> Mode : <strong>{MODE_LABEL[outputMode] ?? outputMode}</strong>
              </li>
              <li className="flex items-center gap-2">
                <span>{prompt.trim() ? '✅' : '⬜'}</span>
                Instruction : <strong>{prompt.trim() ? 'définie' : 'à renseigner'}</strong>
              </li>
            </ul>
            <div className="mt-auto bg-blue-50 border border-blue-100 rounded-lg p-3 text-xs text-blue-800">
              <strong>Prochaine étape :</strong>{' '}
              {selectedIds.size === 0
                ? 'sélectionnez des documents (liste « Documents du rapport » ou Assistant).'
                : !prompt.trim()
                ? 'décrivez le rapport à générer dans « Instructions ».'
                : 'cliquez sur « Générer » en bas.'}
            </div>
          </div>
        )}

        {isGenerating && !contenu && (
          <div className="flex items-center justify-center h-full">
            <LoadingSpinner label="Génération en cours…" />
          </div>
        )}

        {error && (
          <div className="p-4 text-sm text-red-500">{error}</div>
        )}

        {contenu && (
          <div className="p-4">
            {mode === 'preview' ? (
              <div className="prose prose-sm max-w-none prose-headings:font-semibold prose-headings:text-gray-800 prose-p:text-gray-700 prose-li:text-gray-700">
                <ReactMarkdown>{contenu}</ReactMarkdown>
                {isGenerating && (
                  <span className="inline-block w-1 h-4 bg-blue-500 animate-pulse ml-0.5 align-middle" />
                )}
              </div>
            ) : (
              <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono leading-relaxed">
                {contenu}
                {isGenerating && <span className="animate-pulse">▌</span>}
              </pre>
            )}
          </div>
        )}
      </div>

      <PublishBookStackModal
        isOpen={showPublish}
        onClose={() => setShowPublish(false)}
        defaultTitle={contenu ? titreParDefaut(contenu) : ''}
        markdown={contenu}
      />
    </div>
  )
}
