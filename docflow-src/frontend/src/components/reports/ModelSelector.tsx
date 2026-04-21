/**
 * ModelSelector — Sélecteur de modèle Ollama
 * Charge la liste des modèles via le backend (proxy Ollama) pour éviter les CORS.
 */
import { useEffect, useState } from 'react'
import { Cpu } from 'lucide-react'
import { useReportStore } from '../../stores/reportStore'
import { apiClient } from '../../api/client'

// Modèles par défaut si le backend ne répond pas
const MODELES_DEFAUT = [
  { name: 'mixtral:latest', label: 'Mixtral (26 GB) — qualité max' },
  { name: 'mistral:latest', label: 'Mistral (4.4 GB) — rapide' },
  { name: 'llama3.1:latest', label: 'Llama 3.1 (4.9 GB) — polyvalent' },
  { name: 'ministral-3:14b', label: 'Ministral 3 (9.1 GB)' },
]

export default function ModelSelector() {
  const { model, setModel } = useReportStore()
  const [modeles, setModeles] = useState(MODELES_DEFAUT)

  useEffect(() => {
    apiClient.get<{ models: Array<{ name: string }> }>('/generate/models')
      .then(r => {
        if (r.data.models.length > 0) {
          setModeles(r.data.models.map(m => ({ name: m.name, label: m.name })))
        }
      })
      .catch(() => {}) // Silencieux — on garde les défauts
  }, [])

  return (
    <div className="flex items-center gap-2">
      <Cpu size={14} className="text-gray-400 shrink-0" />
      <select
        value={model}
        onChange={e => setModel(e.target.value)}
        className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
      >
        {modeles.map(m => (
          <option key={m.name} value={m.name}>{m.label}</option>
        ))}
      </select>
    </div>
  )
}
