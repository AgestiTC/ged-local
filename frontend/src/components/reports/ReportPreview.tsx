/**
 * ReportPreview — Prévisualisation du rapport généré (Markdown rendu)
 * Affiche le contenu streamé en temps réel + boutons d'export.
 */
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Copy, Download, FileText, RotateCcw, RefreshCw } from 'lucide-react'
import { clsx } from 'clsx'
import { useReportStore } from '../../stores/reportStore'
import { useDocumentStore } from '../../stores/documentStore'
import LoadingSpinner from '../common/LoadingSpinner'
import { useToast } from '../common/Toast'

export default function ReportPreview() {
  const { rapportEnCours, rapportFinal, isGenerating, error, resetRapport, exportPdf, exportDocx, startGeneration } = useReportStore()
  const { selectedIds } = useDocumentStore()
  const [mode, setMode] = useState<'preview' | 'source'>('preview')
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null)
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
          <div className="flex flex-col items-center justify-center h-full text-gray-300 gap-3">
            <FileText size={40} strokeWidth={1} />
            <p className="text-sm">Le rapport apparaîtra ici</p>
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
    </div>
  )
}
