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
import { useCallback, useEffect, useState } from 'react'
import { Cpu, RefreshCw, Zap, Loader2 } from 'lucide-react'
import { useReportStore } from '../../stores/reportStore'
import type { Modeles } from '../../hooks/useModeles'
import { systemApi } from '../../api'
import { useToast } from '../common/Toast'

function sizeLabel(bytes: number) {
  if (!bytes) return ''
  return ` (${(bytes / 1e9).toFixed(1)} GB)`
}

/**
 * Indicateur « modèle prêt / à charger » : dit si le modèle des rapports est résident (génération
 * instantanée) ou à froid, avec un bouton « Préparer » qui le charge à l'avance — utile quand le
 * modèle est gros et lent à charger (évite l'attente au clic « Générer »).
 */
function ModelReadyBadge() {
  const toast = useToast()
  const [charge, setCharge] = useState<boolean | null>(null)
  const [prep, setPrep] = useState(false)

  const rafraichir = useCallback(() => {
    systemApi.modelStatus('rapport').then(s => setCharge(s.charge)).catch(() => setCharge(null))
  }, [])
  useEffect(() => {
    rafraichir()
    const id = setInterval(rafraichir, 20000)   // suit le déchargement/rechargement
    return () => clearInterval(id)
  }, [rafraichir])

  if (charge === null) return null
  if (charge) {
    return <span className="text-xs text-green-600 flex items-center gap-1 shrink-0" title="Le modèle est chargé — la génération démarre sans attente."><Zap size={12} /> prêt</span>
  }
  return (
    <button type="button" disabled={prep}
      onClick={async () => {
        setPrep(true)
        try {
          const r = await systemApi.warmModel('rapport')
          if (r.charge) { toast.success('Modèle préparé'); setCharge(true) }
          else toast.error('Préparation impossible')
        } catch { toast.error('Préparation impossible') } finally { setPrep(false) }
      }}
      title="Charge le modèle à l'avance pour éviter l'attente à la génération"
      className="text-xs text-amber-600 hover:text-amber-700 flex items-center gap-1 shrink-0 disabled:opacity-50">
      {prep ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />} {prep ? 'préparation…' : 'préparer'}
    </button>
  )
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
      <ModelReadyBadge />
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
