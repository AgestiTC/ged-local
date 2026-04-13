/**
 * VersionHistory — Historique des versions d'un document
 * Affiche les versions détectées avec date et résumé des changements.
 */
import { useEffect, useState } from 'react'
import { History, ChevronDown, ChevronRight } from 'lucide-react'
import { documentsApi } from '../../api'
import LoadingSpinner from '../common/LoadingSpinner'

interface Version {
  id: string
  numero_version: number
  hash_sha256: string
  taille_octets?: number
  date_detection: string
  diff_resume?: string
}

interface Props {
  documentId: string
}

function formatBytes(n?: number) {
  if (!n) return '—'
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} Ko`
  return `${(n / 1024 / 1024).toFixed(1)} Mo`
}

export default function VersionHistory({ documentId }: Props) {
  const [versions, setVersions] = useState<Version[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    documentsApi.getVersions(documentId)
      .then(d => setVersions((d.versions as Version[]) ?? []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [documentId])

  if (loading) return <LoadingSpinner size={14} label="Chargement versions…" />

  if (versions.length === 0) {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-400">
        <History size={13} />
        <span>Aucune version antérieure</span>
      </div>
    )
  }

  return (
    <div>
      <button
        onClick={() => setExpanded(e => !e)}
        className="flex items-center gap-2 text-xs text-gray-600 hover:text-gray-800 transition-colors"
      >
        {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <History size={13} />
        <span>{versions.length} version{versions.length > 1 ? 's' : ''} antérieure{versions.length > 1 ? 's' : ''}</span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-2 pl-4 border-l border-gray-200">
          {versions.map(v => (
            <div key={v.id} className="text-xs">
              <div className="flex items-center justify-between">
                <span className="font-medium text-gray-700">v{v.numero_version}</span>
                <span className="text-gray-400">
                  {new Date(v.date_detection).toLocaleDateString('fr-FR', {
                    day: '2-digit', month: '2-digit', year: '2-digit',
                    hour: '2-digit', minute: '2-digit',
                  })}
                </span>
              </div>
              <div className="text-gray-400 font-mono truncate" title={v.hash_sha256}>
                {v.hash_sha256.slice(0, 12)}… · {formatBytes(v.taille_octets)}
              </div>
              {v.diff_resume && (
                <p className="text-gray-600 mt-0.5 italic">{v.diff_resume}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
