/**
 * SearchBar — Barre de recherche hybride GED
 * Composant standalone branché sur gedStore.
 */
import { useRef } from 'react'
import { Search, X } from 'lucide-react'
import { clsx } from 'clsx'
import { useGEDStore } from '../../stores/gedStore'
import type { SearchType } from '../../types'
import LoadingSpinner from '../common/LoadingSpinner'

const TYPES: { value: SearchType; label: string }[] = [
  { value: 'hybrid', label: 'Hybride' },
  { value: 'text', label: 'Texte' },
  { value: 'semantic', label: 'Sémantique' },
]

interface Props {
  className?: string
  autoFocus?: boolean
}

export default function SearchBar({ className, autoFocus }: Props) {
  const { query, searchType, loading, results, setQuery, setSearchType, search, clearResults } = useGEDStore()
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    search()
  }

  return (
    <form onSubmit={handleSubmit} className={clsx('flex items-center gap-2', className)}>
      {/* Input */}
      <div className="flex-1 relative">
        {loading
          ? <LoadingSpinner size={14} className="absolute left-3 top-1/2 -translate-y-1/2" />
          : <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />}
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Rechercher dans vos documents…"
          autoFocus={autoFocus}
          className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
      </div>

      {/* Type selector */}
      <div className="flex border border-gray-200 rounded-lg overflow-hidden">
        {TYPES.map(t => (
          <button
            key={t.value}
            type="button"
            onClick={() => setSearchType(t.value)}
            className={clsx(
              'text-xs px-2.5 py-2 transition-colors',
              searchType === t.value
                ? 'bg-blue-600 text-white'
                : 'text-gray-500 hover:bg-gray-50',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={!query.trim() || loading}
        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg disabled:opacity-40 transition-colors"
      >
        Rechercher
      </button>

      {/* Clear */}
      {(results.length > 0 || query) && (
        <button
          type="button"
          onClick={() => clearResults()}
          className="p-2 text-gray-400 hover:text-gray-700 border border-gray-200 rounded-lg"
          title="Effacer"
        >
          <X size={14} />
        </button>
      )}
    </form>
  )
}
