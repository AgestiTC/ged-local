/**
 * FolderSelector — Navigateur de dossiers système
 * Permet de choisir un chemin via l'API /folders/browse.
 */
import { useEffect, useState } from 'react'
import { Folder, FolderOpen, ChevronRight, Home, X } from 'lucide-react'
import { clsx } from 'clsx'
import { foldersApi, type BrowseResponse } from '../../api'
import LoadingSpinner from '../common/LoadingSpinner'

interface Props {
  onSelect: (path: string) => void
  onClose?: () => void
  initialPath?: string
}

export default function FolderSelector({ onSelect, onClose, initialPath }: Props) {
  const [browse, setBrowse] = useState<BrowseResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [currentPath, setCurrentPath] = useState(initialPath ?? '')

  const load = async (path: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await foldersApi.browse(path)
      setBrowse(data)
      setCurrentPath(data.chemin_actuel)
    } catch {
      setError('Impossible de lire ce dossier')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(currentPath) }, [])

  const navigate = (path: string) => load(path)

  return (
    <div className="flex flex-col h-full bg-white border border-gray-200 rounded-lg overflow-hidden shadow-lg w-80">
      {/* En-tête */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-gray-200 bg-gray-50">
        <FolderOpen size={14} className="text-gray-500 shrink-0" />
        <span className="flex-1 text-xs text-gray-600 truncate font-mono" title={currentPath}>
          {currentPath || 'Racine'}
        </span>
        {onClose && (
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={13} />
          </button>
        )}
      </div>

      {/* Navigation */}
      <div className="flex-1 overflow-y-auto py-1">
        {loading && <LoadingSpinner label="Chargement…" className="justify-center py-6" />}
        {error && <p className="text-xs text-red-500 text-center py-4">{error}</p>}

        {!loading && browse && (
          <>
            {/* Remonter */}
            {browse.chemin_parent !== null && (
              <button
                onClick={() => navigate(browse.chemin_parent!)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-50 transition-colors"
              >
                <Home size={12} />
                <span>Remonter</span>
                <ChevronRight size={12} className="ml-auto text-gray-300" />
              </button>
            )}

            {browse.dossiers.length === 0 && (
              <p className="text-xs text-gray-400 text-center py-4">Aucun sous-dossier</p>
            )}

            {browse.dossiers.map(d => (
              <button
                key={d.chemin}
                onClick={() => navigate(d.chemin)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 transition-colors group"
              >
                <Folder size={13} className="text-yellow-400 shrink-0" />
                <span className="flex-1 text-left truncate">{d.nom}</span>
                <ChevronRight size={11} className="text-gray-300 group-hover:text-gray-500" />
              </button>
            ))}
          </>
        )}
      </div>

      {/* Footer */}
      <div className={clsx(
        'flex items-center gap-2 px-3 py-2 border-t border-gray-200 bg-gray-50',
      )}>
        <span className="flex-1 text-xs text-gray-500 truncate">{currentPath || '—'}</span>
        <button
          onClick={() => { if (currentPath) onSelect(currentPath) }}
          disabled={!currentPath}
          className="text-xs px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white rounded-md transition-colors"
        >
          Sélectionner
        </button>
      </div>
    </div>
  )
}
