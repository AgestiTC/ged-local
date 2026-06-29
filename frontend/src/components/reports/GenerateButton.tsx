/**
 * GenerateButton — Bouton de lancement de génération
 * Standalone : lit le store et affiche l'état en temps réel.
 */
import { Play, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { useDocumentStore } from '../../stores/documentStore'
import { useReportStore } from '../../stores/reportStore'

interface Props {
  className?: string
}

export default function GenerateButton({ className }: Props) {
  const { selectedIds } = useDocumentStore()
  const { prompt, isGenerating, startGeneration, outputMode } = useReportStore()

  // En mode « Tuto wiki », les documents sources sont optionnels (rédaction from scratch possible).
  const isWiki = outputMode === 'wiki'
  const canGenerate = prompt.trim().length > 0 && !isGenerating && (isWiki || selectedIds.size > 0)

  const nbDocs = selectedIds.size
  const label = isGenerating
    ? 'Génération en cours…'
    : !isWiki && nbDocs === 0
    ? 'Sélectionnez des documents'
    : !prompt.trim()
    ? (isWiki ? 'Décrivez le tuto à rédiger' : 'Entrez une instruction')
    : isWiki
    ? (nbDocs > 0 ? `Rédiger le tuto (${nbDocs} doc${nbDocs > 1 ? 's' : ''})` : 'Rédiger le tuto')
    : `Générer (${nbDocs} doc${nbDocs > 1 ? 's' : ''})`

  return (
    <button
      onClick={() => startGeneration([...selectedIds])}
      disabled={!canGenerate}
      className={clsx(
        'flex items-center justify-center gap-2 w-full py-3 rounded-lg font-semibold text-sm transition-all',
        canGenerate
          ? 'bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white shadow-sm'
          : 'bg-gray-100 text-gray-400 cursor-not-allowed',
        className,
      )}
    >
      {isGenerating
        ? <Loader2 size={15} className="animate-spin" />
        : <Play size={15} fill={canGenerate ? 'white' : 'currentColor'} />}
      {label}
    </button>
  )
}
