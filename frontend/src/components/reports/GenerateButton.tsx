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
  const { prompt, isGenerating, startGeneration } = useReportStore()

  const canGenerate = selectedIds.size > 0 && prompt.trim().length > 0 && !isGenerating

  const label = isGenerating
    ? 'Génération en cours…'
    : selectedIds.size === 0
    ? 'Sélectionnez des documents'
    : !prompt.trim()
    ? 'Entrez une instruction'
    : `Générer (${selectedIds.size} doc${selectedIds.size > 1 ? 's' : ''})`

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
