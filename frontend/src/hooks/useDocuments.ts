/**
 * Hook useDocuments — wrapper fin sur documentStore
 * Expose les données et actions les plus courantes.
 */
import { useDocumentStore } from '../stores/documentStore'

export function useDocuments() {
  const {
    documents, total, page, loading, error,
    selectedIds, uploadJobs,
    fetchDocuments,
    toggleSelect, selectAll, deselectAll, isSelected,
    selectDocument, deselectDocument,
    uploadFiles,
    deleteDocument,
    relaunchExtraction,
    clearUploadJobs,
  } = useDocumentStore()

  return {
    documents,
    total,
    page,
    loading,
    error,
    selectedIds,
    uploadJobs,
    selectedCount: selectedIds.size,
    fetchDocuments,
    toggleSelect,
    selectAll,
    deselectAll,
    isSelected,
    selectDocument,
    deselectDocument,
    uploadFiles,
    deleteDocument,
    relaunchExtraction,
    clearUploadJobs,
  }
}
