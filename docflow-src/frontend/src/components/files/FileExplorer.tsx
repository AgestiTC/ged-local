/**
 * FileExplorer — Arborescence des documents indexés avec sélection
 * Affiche les documents par statut avec indicateur coloré.
 * Supporte la sélection simple, Ctrl+clic (multi), et tout sélectionner.
 */
import { useEffect, useState } from 'react'
import { FileText, RefreshCw, Trash2, CheckSquare, Square } from 'lucide-react'
import { clsx } from 'clsx'
import { useDocumentStore } from '../../stores/documentStore'
import LoadingSpinner from '../common/LoadingSpinner'
import type { Document } from '../../types'

function formatBytes(n?: number) {
  if (!n) return '—'
  if (n < 1024) return `${n} o`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} Ko`
  return `${(n / 1024 / 1024).toFixed(1)} Mo`
}

function StatutDot({ statut }: { statut: Document['statut'] }) {
  return (
    <span
      title={statut}
      className={clsx('w-2 h-2 rounded-full shrink-0 mt-1', {
        'bg-green-400': statut === 'enriched',
        'bg-yellow-400 animate-pulse': statut === 'extracted' || statut === 'pending',
        'bg-red-400': statut === 'error',
      })}
    />
  )
}

export default function FileExplorer() {
  const {
    documents, total, loading, error,
    selectedIds, fetchDocuments,
    toggleSelect, selectAll, deselectAll, isSelected,
    deleteDocument, relaunchExtraction,
    uploadJobs,
  } = useDocumentStore()

  const [filter, setFilter] = useState('')

  useEffect(() => { fetchDocuments() }, [])

  const filtered = filter
    ? documents.filter(d => d.nom.toLowerCase().includes(filter.toLowerCase()))
    : documents

  const allSelected = filtered.length > 0 && filtered.every(d => isSelected(d.id))

  return (
    <div className="flex flex-col h-full gap-2">
      {/* En-tête */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500 font-medium">
          {selectedIds.size > 0 ? `${selectedIds.size} sélectionné(s)` : `${total} document(s)`}
        </span>
        <button onClick={() => fetchDocuments()} className="text-gray-400 hover:text-gray-600" title="Actualiser">
          <RefreshCw size={13} />
        </button>
      </div>

      {/* Filtre */}
      <input
        type="search"
        placeholder="Filtrer…"
        value={filter}
        onChange={e => setFilter(e.target.value)}
        className="w-full px-2.5 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400"
      />

      {/* Tout sélectionner */}
      {filtered.length > 0 && (
        <button
          onClick={() => (allSelected ? deselectAll() : selectAll())}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700"
        >
          {allSelected ? <CheckSquare size={13} /> : <Square size={13} />}
          {allSelected ? 'Tout désélectionner' : 'Tout sélectionner'}
        </button>
      )}

      {/* Jobs en cours */}
      {uploadJobs.length > 0 && (
        <div className="space-y-1">
          {uploadJobs.map((j, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 px-2 py-1.5 rounded-md">
              <div className={clsx('w-2 h-2 rounded-full shrink-0', {
                'bg-yellow-400 animate-pulse': j.statut === 'en_attente' || j.statut === 'running',
                'bg-green-400': j.statut === 'completed',
                'bg-red-400': j.statut === 'failed' || j.statut === 'erreur',
              })} />
              <span className="truncate flex-1">{j.fichier}</span>
              {(j.progress ?? 0) < 100 && j.progress !== undefined && <span>{j.progress}%</span>}
            </div>
          ))}
        </div>
      )}

      {/* Liste documents */}
      <div className="flex-1 overflow-y-auto space-y-0.5 min-h-0">
        {loading && <LoadingSpinner label="Chargement…" className="py-4 justify-center" />}
        {error && <p className="text-xs text-red-500 py-2">{error}</p>}
        {!loading && filtered.length === 0 && (
          <p className="text-xs text-gray-400 py-4 text-center">Aucun document indexé</p>
        )}

        {filtered.map(doc => (
          <div
            key={doc.id}
            onClick={() => toggleSelect(doc.id)}
            className={clsx(
              'flex items-start gap-2 px-2 py-1.5 rounded-md cursor-pointer group transition-colors text-xs',
              isSelected(doc.id) ? 'bg-blue-50 border border-blue-200' : 'hover:bg-gray-50 border border-transparent',
            )}
          >
            <StatutDot statut={doc.statut} />
            <FileText size={13} className="text-gray-400 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="truncate font-medium text-gray-800">{doc.nom}</p>
              <p className="text-gray-400">{doc.extension.toUpperCase()} · {formatBytes(doc.taille_octets)}</p>
            </div>
            <div className="flex gap-1 opacity-0 group-hover:opacity-100 shrink-0">
              {doc.statut === 'error' && (
                <button onClick={e => { e.stopPropagation(); relaunchExtraction(doc.id) }} title="Relancer">
                  <RefreshCw size={11} className="text-orange-400 hover:text-orange-600" />
                </button>
              )}
              <button onClick={e => { e.stopPropagation(); deleteDocument(doc.id) }} title="Supprimer">
                <Trash2 size={11} className="text-red-400 hover:text-red-600" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
