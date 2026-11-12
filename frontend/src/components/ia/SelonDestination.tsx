/**
 * SelonDestination — texte qui dépend de la destination de l'IA, pour que les mentions « 100% local »
 * restent exactes dans les trois états (local lu, GECO, inconnu). Un seul composant plutôt que des copies.
 */
import type { ReactNode } from 'react'
import { useIaDestinationStore } from '../../stores/iaDestinationStore'
import type { EtatIa } from '../../utils/iaDestination'

/** Choix pur (testable) du contenu selon l'état : jamais le texte « local » tant que l'état n'est pas lu. */
export function choisirSelonDestination(
  destination: EtatIa, c: { local: ReactNode; geco: ReactNode; inconnu: ReactNode },
): ReactNode {
  return destination === 'local' ? c.local : destination === 'geco' ? c.geco : c.inconnu
}

export function SelonDestination(props: { local: ReactNode; geco: ReactNode; inconnu: ReactNode }) {
  const destination = useIaDestinationStore(s => s.destination)
  return <>{choisirSelonDestination(destination, props)}</>
}
