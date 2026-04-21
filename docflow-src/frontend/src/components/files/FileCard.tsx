/**
 * FileCard — Carte compacte d'un document
 * Affiche le nom, l'extension, le statut et les actions rapides.
 */
import { FileText, Trash2, RefreshCw, CheckSquare, Square } from 'lucide-react'
import { clsx } from 'clsx'
import type { Document } from '../../types'

interface Props {
  document: Document
  selected?: boolean
  onToggle?: (id: string) => void
  onDelete?: (id: string) => void
  onRelaunch?: (id: string) => void
}

const STATUS_DOT: Record<string, string> = {
  enriched:  'bg-green-400',
  extracted: 'bg-yellow-400',
  pending:   'bg-yellow-300',
  error:     'bg-red-400',
}

function formatBytes(n?: number) {
  if (!n) return ''
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} Ko`
  return `${(n / 1024 / 1024).toFixed(1)} Mo`
}

export default function FileCard({ document: doc, selected, onToggle, onDelete, onRelaunch }: Props) {
  const dot = STATUS_DOT[doc.statut] ?? 'bg-gray-300'

  return (
    <div
      onClick={() => onToggle?.(doc.id)}
      className={clsx(
        'group flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors text-xs',
        selected ? 'bg-blue-50' : 'hover:bg-gray-50',
      )}
    >
      {/* Checkbox */}
      <span className="shrink-0 text-blue-600">
        {selected
          ? <CheckSquare size={13} />
          : <Square size={13} className="text-gray-300" />}
      </span>

      {/* Icône + dot statut */}
      <div className="relative shrink-0">
        <FileText size={13} className="text-gray-400" />
        <span className={clsx('absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full border border-white', dot)} />
      </div>

      {/* Nom + taille */}
      <div className="flex-1 min-w-0">
        <p className={clsx('truncate', selected ? 'text-blue-700 font-medium' : 'text-gray-700')} title={doc.nom}>
          {doc.nom}
        </p>
        {doc.taille_octets && (
          <p className="text-gray-400">{formatBytes(doc.taille_octets)}</p>
        )}
      </div>

      {/* Actions (hover) */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
        {doc.statut === 'error' && onRelaunch && (
          <button
            onClick={e => { e.stopPropagation(); onRelaunch(doc.id) }}
            className="text-orange-400 hover:text-orange-600"
            title="Relancer"
          >
            <RefreshCw size={11} />
          </button>
        )}
        {onDelete && (
          <button
            onClick={e => { e.stopPropagation(); onDelete(doc.id) }}
            className="text-red-400 hover:text-red-600"
            title="Supprimer"
          >
            <Trash2 size={11} />
          </button>
        )}
      </div>
    </div>
  )
}
