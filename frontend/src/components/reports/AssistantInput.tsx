/**
 * AssistantInput — saisie du besoin pour l'Assistant « Trouver des documents »
 * ============================================================================
 * Compact : il vit dans l'étape ② (onglet « Assistant IA »). Les PROPOSITIONS
 * résultantes s'affichent dans le panneau « Résultat » à droite (AssistantProposals).
 */
import { Sparkles, Loader2 } from 'lucide-react'
import { useReportAssistantStore } from '../../stores/reportAssistantStore'
import { useToast } from '../common/Toast'

export default function AssistantInput() {
  const toast = useToast()
  const { besoin, setBesoin, loading, proposer } = useReportAssistantStore()

  const lancer = async () => {
    try {
      const total = await proposer()
      if (total === 0) toast.info('Aucun fichier connu ne correspond — affine le besoin.')
      else if (total !== null) toast.success(`${total} fichier(s) proposé(s) → voir « Documents proposés » à droite.`)
    } catch {
      toast.error('Assistant indisponible (Ollama ?)')
    }
  }

  return (
    <div className="space-y-2.5">
      <p className="text-xs text-gray-500">
        Décris ton besoin : l'IA déduit les <strong>pièces attendues</strong> et propose les fichiers connus.
        Les propositions s'affichent dans <strong>« Résultat »</strong> → coche-les pour les ajouter.
      </p>
      <textarea
        value={besoin}
        onChange={e => setBesoin(e.target.value)}
        placeholder="Ex : « j'ai besoin de documents pour un dossier de location », « monter un dossier d'appel d'offres »…"
        rows={3}
        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-blue-400"
      />
      <button
        type="button"
        onClick={lancer}
        disabled={loading || besoin.trim().length < 3}
        className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-40"
      >
        {loading ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
        {loading ? 'Recherche…' : 'Proposer des documents'}
      </button>
    </div>
  )
}
