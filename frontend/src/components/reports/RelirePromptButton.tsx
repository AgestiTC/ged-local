/**
 * RelirePromptButton — « Faire relire par l'IA ».
 * ===============================================
 * L'IA locale propose une version structurée du prompt (rôle, tâche, règles, barème, format) et
 * dit ce qui manque (« [à préciser : …] »). La proposition s'affiche à côté : RIEN n'est remplacé
 * sans l'accord de l'utilisateur (demande du 11/10/2026). Utilisé dans les Instructions de Créer et
 * dans Paramètres › Génération.
 */
import { useState } from 'react'
import { Loader2, Sparkles, Check, X } from 'lucide-react'
import { promptsApi } from '../../api'
import { useToast } from '../common/Toast'

interface Props {
  texte: string
  /** Mode de la page Créer : en « comparatif », le prompt ne règle que le contenu des valeurs JSON. */
  mode?: string
  model?: string
  onRemplacer: (nouveau: string) => void
}

export default function RelirePromptButton({ texte, mode, model, onRemplacer }: Props) {
  const [chargement, setChargement] = useState(false)
  const [proposition, setProposition] = useState<{ prompt: string; remarques: string[] } | null>(null)
  const toast = useToast()

  const relire = async () => {
    if (!texte.trim()) { toast.error('Écrivez d\'abord un prompt à faire relire'); return }
    setChargement(true)
    try {
      const r = await promptsApi.relire({ texte, mode, model: model || undefined })
      setProposition({ prompt: r.prompt, remarques: r.remarques })
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Relecture impossible (Ollama ?)')
    } finally {
      setChargement(false)
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={relire}
        disabled={chargement}
        className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border border-violet-200 bg-violet-50 text-violet-700 hover:bg-violet-100 disabled:opacity-60 transition-colors"
        title="L'IA locale propose une version structurée — vous choisissez de la garder ou non"
      >
        {chargement ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
        {chargement ? 'Relecture en cours…' : 'Faire relire par l\'IA'}
      </button>

      {proposition && (
        <div className="rounded-lg border border-violet-200 bg-violet-50/40 p-3 space-y-2 text-xs">
          <p className="font-semibold text-violet-900">Proposition de l'IA</p>
          <pre className="whitespace-pre-wrap font-sans text-gray-800 bg-white border border-gray-200 rounded-md p-2.5 max-h-72 overflow-y-auto leading-relaxed">
            {proposition.prompt}
          </pre>
          {proposition.remarques.length > 0 && (
            <ul className="list-disc pl-4 text-gray-600 space-y-0.5">
              {proposition.remarques.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
          {proposition.prompt.includes('[à préciser') && (
            <p className="text-amber-700">Complétez les « [à préciser : …] » après remplacement.</p>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => { onRemplacer(proposition.prompt); setProposition(null); toast.success('Prompt remplacé') }}
              className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-violet-600 text-white hover:bg-violet-700"
            >
              <Check size={12} /> Remplacer mon prompt
            </button>
            <button
              type="button"
              onClick={() => setProposition(null)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50"
            >
              <X size={12} /> Garder le mien
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
