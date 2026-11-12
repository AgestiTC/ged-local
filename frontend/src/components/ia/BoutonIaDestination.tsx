/**
 * BoutonIaDestination — le bouton « IA LOCAL | IA GECO » de l'en-tête (et des Paramètres).
 * Deux positions écrites en toutes lettres, l'état courant porté par `aria-pressed` ET la couleur
 * (vert foncé = local, ambre foncé = internet) ; aucune position pressée tant que l'état est inconnu.
 * ADMINISTRATEUR SEUL : pour le rôle Utilisateur le bouton n'est pas rendu du tout (il garde l'INFORMATION :
 * bandeau, badges, libellé « Auto », vérification avant envoi). Passer sur GECO ouvre la confirmation (jamais
 * d'écriture directe) ; « IA LOCAL » reste TOUJOURS actif pour l'admin, même sur un écran qui affiche
 * déjà local (arrêt d'urgence quand l'écran est périmé).
 */
import { clsx } from 'clsx'
import { useIaDestinationStore } from '../../stores/iaDestinationStore'
import { useAuthStore } from '../../stores/authStore'
import { estAdmin } from '../../utils/acces'
import type { EtatIa } from '../../utils/iaDestination'
import { useActionsIa } from './useActionsIa'

interface Props {
  destination: EtatIa
  admin: boolean
  occupe: boolean
  /** La dernière lecture a échoué : l'état affiché n'est pas vérifié (pastille discrète). */
  nonVerifie?: boolean
  onLocal: () => void
  onGeco: () => void
}

export function BoutonIaDestinationVue({ destination, admin, occupe, nonVerifie, onLocal, onGeco }: Props) {
  if (!admin) return null
  const aide = "Où partent les demandes interactives (chat, rapports, comparatifs). IA GECO = par internet, après confirmation ; l'indexation reste locale."
  const base = 'px-2 py-0.5 text-[11px] font-bold tracking-wide whitespace-nowrap transition-colors '
    + 'focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-400 disabled:cursor-default'
  return (
    <div role="group" aria-label="Destination de l'IA" title={aide} aria-busy={occupe}
      className="flex items-center gap-1 shrink-0">
      <div className="flex rounded-full border border-gray-400 overflow-hidden bg-white">
        <button type="button" aria-pressed={destination === 'local'} disabled={occupe}
          title="Revenir à l'IA locale (immédiat)"
          onClick={onLocal}
          className={clsx(base, destination === 'local' ? 'bg-emerald-800 text-white' : 'text-gray-700 enabled:hover:bg-gray-100')}>
          IA LOCAL
        </button>
        <button type="button" aria-pressed={destination === 'geco'} disabled={occupe}
          title="Passer sur IA GECO (internet) — demande une confirmation"
          onClick={() => { if (destination !== 'geco') onGeco() }}
          className={clsx(base, destination === 'geco' ? 'bg-amber-200 text-amber-950' : 'text-gray-700 enabled:hover:bg-gray-100')}>
          {occupe ? '…' : 'IA GECO'}
        </button>
      </div>
      {(nonVerifie || destination === 'inconnu') && (
        <span role="img" aria-label="état non vérifié"
          title={destination === 'inconnu'
            ? "Destination de l'IA en cours de vérification."
            : "État non vérifié : la dernière lecture de la destination de l'IA a échoué."}
          className="w-2 h-2 rounded-full bg-amber-500 shrink-0 cursor-help" />
      )}
    </div>
  )
}

/** `listeDisponible` : fourni par les Paramètres (qui lisent la liste GECO) ; l'en-tête l'ignore. */
export default function BoutonIaDestination({ listeDisponible }: { listeDisponible?: boolean }) {
  const destination = useIaDestinationStore(s => s.destination)
  const occupe = useIaDestinationStore(s => s.enCours)
  const nonVerifie = useIaDestinationStore(s => s.erreurLecture)
  const admin = useAuthStore(s => estAdmin(s))
  const { versGeco, versLocal } = useActionsIa()
  return (
    <BoutonIaDestinationVue destination={destination} admin={admin} occupe={occupe} nonVerifie={nonVerifie}
      onLocal={versLocal} onGeco={() => versGeco(listeDisponible)} />
  )
}
