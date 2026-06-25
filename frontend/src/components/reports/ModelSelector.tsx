/**
 * ModelSelector — Sélecteur de modèle Ollama (liste dynamique + rafraîchir)
 * Les modèles sont récupérés en direct depuis Ollama via le backend
 * (`/api/system/models`). Bouton ♻️ pour recharger la liste.
 */
import { useCallback, useEffect, useState } from 'react'
import { Cpu, RefreshCw } from 'lucide-react'
import { useReportStore } from '../../stores/reportStore'
import { systemApi, type OllamaModel } from '../../api'

function sizeLabel(bytes: number) {
  if (!bytes) return ''
  return ` (${(bytes / 1e9).toFixed(1)} GB)`
}

export default function ModelSelector() {
  const { model, setModel } = useReportStore()
  const [modeles, setModeles] = useState<OllamaModel[]>([])
  const [loading, setLoading] = useState(false)
  const [erreur, setErreur] = useState(false)

  const charger = useCallback(async () => {
    setLoading(true)
    setErreur(false)
    try {
      const { models, defaut } = await systemApi.models()
      setModeles(models)
      // Si le modèle courant n'est pas/plus dans la liste, prendre le défaut
      if (models.length && !models.some(m => m.name === model)) {
        setModel(defaut && models.some(m => m.name === defaut) ? defaut : models[0].name)
      }
    } catch {
      setErreur(true)
    } finally {
      setLoading(false)
    }
  }, [model, setModel])

  useEffect(() => { charger() }, []) // eslint-disable-line react-hooks/exhaustive-deps

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
        {modeles.map(m => (
          <option key={m.name} value={m.name}>{m.name}{sizeLabel(m.size)}</option>
        ))}
      </select>
      <button
        type="button"
        onClick={charger}
        disabled={loading}
        title="Rafraîchir la liste des modèles installés"
        className="p-1.5 rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-50"
      >
        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
      </button>
    </div>
  )
}
