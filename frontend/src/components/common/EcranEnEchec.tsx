/**
 * EcranEnEchec — ce qu'on affiche quand un écran n'a pas pu charger
 * =================================================================
 * **Jamais une page blanche.** Le réflexe `if (!data) return null` produit un écran vide et
 * une alerte rouge sans cause : l'utilisateur ne sait pas s'il doit attendre, recharger ou
 * signaler, et le diagnostic impose d'aller lire les logs du serveur pour une panne qui
 * aurait pu se comprendre d'un coup d'œil.
 *
 * Un écran qui échoue doit dire **quoi**, et proposer de **réessayer** — le cas le plus
 * fréquent étant un backend qui redémarre encore après un déploiement.
 *
 * *(Écrit après un incident où « Synthèse fiscale indisponible » s'affichait sur une page
 * vide alors que l'API répondait 200 sur les trois routes d'accès.)*
 */
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  titre: string
  /** La cause remontée par le serveur, ou le code HTTP. Absente si on ne la connaît pas. */
  cause?: string | null
  onReessayer: () => void
}

export default function EcranEnEchec({ titre, cause, onReessayer }: Props) {
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      <AlertTriangle size={28} className="text-amber-500" />
      <p className="text-sm font-medium text-gray-700">{titre}</p>
      {cause && <p className="text-xs text-gray-500 max-w-md break-words">{cause}</p>}
      <p className="text-xs text-gray-400 max-w-md">
        Si un déploiement vient d'avoir lieu, le serveur redémarre peut-être encore.
      </p>
      <button type="button" onClick={onReessayer}
        className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700">
        <RefreshCw size={14} /> Réessayer
      </button>
    </div>
  )
}

/**
 * Extrait une cause lisible d'une erreur axios : le détail rendu par le serveur d'abord,
 * puis le code HTTP, puis le message brut. Un « indisponible » sans cause oblige à fouiller
 * les logs pour un incident qui aurait pu se diagnostiquer à l'écran.
 */
export function causeLisible(e: unknown): string {
  const r = e as { response?: { status?: number; data?: { detail?: string } }; message?: string }
  return r?.response?.data?.detail
    || (r?.response?.status ? `Le serveur a répondu ${r.response.status}.` : '')
    || r?.message
    || 'Cause inconnue.'
}
