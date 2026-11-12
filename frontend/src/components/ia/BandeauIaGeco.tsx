/**
 * BandeauIaGeco — bandeau PERMANENT, sur toutes les pages, tant que l'IA GECO est activée.
 * Condition de Thomas (12/11/2026) : la bascule vers internet doit rester visible. Couleur
 * d'avertissement (ambre), pas le rouge d'une erreur : ce n'est pas une panne, c'est un état à ne pas oublier.
 * Rendu dans le flux de la page (pas en `fixed`) : il ne recouvre rien et passe à la ligne sur tablette.
 */
import { Globe } from 'lucide-react'
import { useIaDestinationStore } from '../../stores/iaDestinationStore'
import { useAuthStore } from '../../stores/authStore'
import { estAdmin } from '../../utils/acces'
import { texteBandeau, type EtatIa } from '../../utils/iaDestination'
import { useActionsIa } from './useActionsIa'

interface Props { destination: EtatIa; gecoModele: string; admin: boolean; onRevenir: () => void }

export function BandeauIaGecoVue({ destination, gecoModele, admin, onRevenir }: Props) {
  if (destination !== 'geco') return null
  return (
    <div role="status" aria-live="polite"
      className="shrink-0 flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5 bg-amber-100 border-b border-amber-300 text-amber-900 text-xs sm:text-sm">
      <Globe size={15} className="shrink-0" aria-hidden="true" />
      <span className="flex-1 min-w-0 font-medium">{texteBandeau(gecoModele)}</span>
      {admin && (
        <button type="button" onClick={onRevenir}
          className="shrink-0 px-2.5 py-1 rounded-md border border-amber-400 bg-white/70 text-amber-900 font-semibold hover:bg-white">
          Revenir à l'IA locale
        </button>
      )}
    </div>
  )
}

export default function BandeauIaGeco() {
  const destination = useIaDestinationStore(s => s.destination)
  const gecoModele = useIaDestinationStore(s => s.gecoModele)
  const admin = useAuthStore(s => estAdmin(s))
  const { versLocal } = useActionsIa()
  return <BandeauIaGecoVue destination={destination} gecoModele={gecoModele} admin={admin} onRevenir={versLocal} />
}
