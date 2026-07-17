/**
 * ModelSelector — Sélecteur de modèle Ollama (liste dynamique + rafraîchir)
 * =========================================================================
 * NE charge PLUS lui-même : la liste vient de `useModeles()`, appelé par la PAGE.
 * Raison : ce composant est monté seulement quand l'utilisateur déplie le réglage —
 * y mettre le chargement/l'auto-réparation revenait à ne jamais les exécuter dans le
 * cas à couvrir (c'était le bug « mixtral »).
 *
 * « Auto » (valeur `''`) = on n'impose rien, le backend route selon la config par usage.
 */
import { Cpu, RefreshCw } from 'lucide-react'
import { useReportStore } from '../../stores/reportStore'
import type { Modeles } from '../../hooks/useModeles'

function sizeLabel(bytes: number) {
  if (!bytes) return ''
  return ` (${(bytes / 1e9).toFixed(1)} GB)`
}

export default function ModelSelector({ modeles, defaut, loading, erreur, recharger }: Modeles) {
  const { model, setModel } = useReportStore()

  return (
    <div className="flex items-center gap-2">
      <Cpu size={14} className="text-gray-400 shrink-0" />
      <select
        value={model}
        onChange={e => setModel(e.target.value)}
        disabled={loading || modeles.length === 0}
        className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:bg-gray-50"
      >
        {modeles.length === 0 && (
          <option>{erreur ? 'Ollama injoignable' : 'Chargement…'}</option>
        )}
        {/* Toujours pouvoir REVENIR au routage automatique après un choix manuel. */}
        {modeles.length > 0 && (
          <option value="">Auto{defaut ? ` — ${defaut}` : ''}</option>
        )}
        {modeles.map(m => (
          <option key={m.name} value={m.name}>{m.name}{sizeLabel(m.size)}</option>
        ))}
      </select>
      <button
        type="button"
        onClick={recharger}
        disabled={loading}
        title="Rafraîchir la liste des modèles installés"
        className="p-1.5 rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-50"
      >
        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
      </button>
    </div>
  )
}
