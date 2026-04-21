/**
 * CompareProgress — Barre de progression du rapport comparatif.
 * Se connecte au flux SSE et affiche l'avancement par groupe.
 * Déclenche le téléchargement automatique à la fin.
 */
import { useEffect, useRef, useState } from 'react'
import { CheckCircle, Circle, Loader, XCircle, Download } from 'lucide-react'
import { clsx } from 'clsx'
import { compareApi } from '../../api'
import type { CompareEvent } from '../../types'

interface GroupeEtat {
  nom: string
  statut: 'pending' | 'running' | 'done' | 'error'
}

interface Props {
  jobId: string
  groupeNoms: string[]
  onComplete: () => void
  onError: (msg: string) => void
}

export default function CompareProgress({ jobId, groupeNoms, onComplete, onError }: Props) {
  const [etats, setEtats] = useState<GroupeEtat[]>(
    groupeNoms.map(nom => ({ nom, statut: 'pending' }))
  )
  const [done, setDone] = useState(false)
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    const url = compareApi.getStreamUrl(jobId)
    const es = new EventSource(url)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as CompareEvent

        if (event.statut === 'running' && event.groupe) {
          setEtats(prev => prev.map(g =>
            g.nom === event.groupe ? { ...g, statut: 'running' } : g
          ))
        } else if (event.statut === 'done' && event.groupe) {
          setEtats(prev => prev.map(g =>
            g.nom === event.groupe ? { ...g, statut: 'done' } : g
          ))
        } else if (event.statut === 'complete') {
          es.close()
          setDone(true)
          const url = compareApi.getDownloadUrl(jobId)
          setDownloadUrl(url)
          // Téléchargement automatique
          const a = document.createElement('a')
          a.href = url
          a.download = `comparatif.xlsx`
          a.click()
          onComplete()
        } else if (event.statut === 'failed') {
          es.close()
          setEtats(prev => prev.map(g =>
            g.statut === 'running' ? { ...g, statut: 'error' } : g
          ))
          onError(event.erreur || 'Erreur lors de la comparaison')
        }
      } catch { /* ignorer */ }
    }

    es.onerror = () => {
      es.close()
      onError('Connexion SSE interrompue')
    }

    return () => es.close()
  }, [jobId])

  const nbDone = etats.filter(g => g.statut === 'done').length
  const total = etats.length
  const pct = total > 0 ? Math.round((nbDone / total) * 100) : 0

  return (
    <div className="space-y-4">
      {/* Barre de progression globale */}
      <div>
        <div className="flex justify-between items-center mb-1.5">
          <span className="text-xs font-medium text-gray-600">
            {done ? 'Terminé !' : `Analyse en cours… ${nbDone}/${total}`}
          </span>
          <span className="text-xs text-gray-400">{pct}%</span>
        </div>
        <div className="w-full bg-gray-100 rounded-full h-2">
          <div
            className={clsx(
              'h-2 rounded-full transition-all duration-500',
              done ? 'bg-green-500' : 'bg-blue-500'
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* État par groupe */}
      <div className="space-y-1.5">
        {etats.map(groupe => (
          <div key={groupe.nom} className="flex items-center gap-2.5 text-xs">
            {groupe.statut === 'done' && <CheckCircle size={14} className="text-green-500 shrink-0" />}
            {groupe.statut === 'running' && <Loader size={14} className="text-blue-500 animate-spin shrink-0" />}
            {groupe.statut === 'pending' && <Circle size={14} className="text-gray-300 shrink-0" />}
            {groupe.statut === 'error' && <XCircle size={14} className="text-red-400 shrink-0" />}
            <span className={clsx(
              'truncate',
              groupe.statut === 'done' && 'text-gray-700 font-medium',
              groupe.statut === 'running' && 'text-blue-600 font-medium',
              groupe.statut === 'pending' && 'text-gray-400',
              groupe.statut === 'error' && 'text-red-400',
            )}>
              {groupe.nom}
            </span>
            {groupe.statut === 'running' && (
              <span className="text-blue-400 ml-auto shrink-0">analyse…</span>
            )}
            {groupe.statut === 'done' && (
              <span className="text-green-500 ml-auto shrink-0">✓</span>
            )}
          </div>
        ))}
      </div>

      {/* Bouton téléchargement manuel si auto-download bloqué */}
      {done && downloadUrl && (
        <a
          href={downloadUrl}
          download="comparatif.xlsx"
          className="flex items-center justify-center gap-2 w-full py-2 bg-green-600 hover:bg-green-700 text-white text-xs font-medium rounded-lg transition-colors"
        >
          <Download size={13} />
          Télécharger le rapport Excel
        </a>
      )}
    </div>
  )
}
