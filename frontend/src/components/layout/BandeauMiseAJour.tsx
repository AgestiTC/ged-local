/**
 * Bandeau « une nouvelle version est en ligne — recharger ».
 *
 * Il ne recharge pas tout seul : un rechargement automatique jetterait une fiche en cours
 * d'édition ou un rapport en train de se générer. Le bandeau prévient, l'utilisateur choisit
 * son moment. Il est aussi masquable — mais il reviendra au prochain sondage, parce que le
 * fait qu'on tourne sur une version périmée, lui, ne disparaît pas.
 *
 * Détection : voir `hooks/useMiseAJour`.
 */
import { useState } from 'react'
import { RefreshCw, Sparkles, X } from 'lucide-react'
import { useMiseAJour } from '../../hooks/useMiseAJour'

export default function BandeauMiseAJour() {
  const { disponible, version } = useMiseAJour()
  const [masque, setMasque] = useState(false)

  if (!disponible || masque) return null

  return (
    <div role="status"
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-2.5
                 bg-blue-600 text-white rounded-lg shadow-lg max-w-[92vw]">
      <Sparkles size={16} className="shrink-0" />
      <p className="text-sm">
        Une nouvelle version {version && <strong>({version}) </strong>}est en ligne.
        <span className="hidden sm:inline text-blue-100"> Cet onglet tourne encore sur l'ancienne.</span>
      </p>
      <button type="button" onClick={() => window.location.reload()}
        className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium bg-white text-blue-700
                   rounded-md hover:bg-blue-50 transition-colors shrink-0">
        <RefreshCw size={14} /> Recharger
      </button>
      <button type="button" onClick={() => setMasque(true)}
        aria-label="Masquer" title="Masquer — le bandeau reviendra"
        className="p-1 text-blue-200 hover:text-white shrink-0">
        <X size={15} />
      </button>
    </div>
  )
}
