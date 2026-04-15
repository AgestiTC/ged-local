/**
 * Hook useReport — wrapper fin sur reportStore
 * Expose la configuration et l'état de génération.
 */
import { useReportStore } from '../stores/reportStore'
import { useDocumentStore } from '../stores/documentStore'

export function useReport() {
  const {
    prompt, model, outputMode,
    isGenerating, jobId, rapportEnCours, rapportFinal, error,
    historique,
    setPrompt, setModel, setOutputMode,
    startGeneration,
    cancelGeneration,
    resetRapport,
    exportPdf,
    exportDocx,
  } = useReportStore()

  const { selectedIds } = useDocumentStore()

  const canGenerate = selectedIds.size > 0 && prompt.trim().length > 0 && !isGenerating

  const generate = () => startGeneration([...selectedIds])

  return {
    prompt,
    model,
    outputMode,
    isGenerating,
    jobId,
    rapportEnCours,
    rapportFinal,
    error,
    historique,
    canGenerate,
    selectedCount: selectedIds.size,
    setPrompt,
    setModel,
    setOutputMode,
    generate,
    cancelGeneration,
    resetRapport,
    exportPdf,
    exportDocx,
  }
}
