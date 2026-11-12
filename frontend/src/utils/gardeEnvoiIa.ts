/**
 * gardeEnvoiIa — garde PARTAGÉE avant tout envoi interactif à l'IA (chat, rapport, comparatif…).
 * Relit la destination de l'IA (« local » / « geco ») de force, puis décide : on n'envoie jamais sur un
 * état périmé, et jamais vers GECO sans que l'utilisateur ait vu le bandeau. Voir `decisionEnvoi`.
 *
 * Usage :  const refus = await refusEnvoiIa()
 *          if (refus) { toast.error(refus); return }
 */
import { useIaDestinationStore } from '../stores/iaDestinationStore'
import { decisionEnvoi } from './iaDestination'

/** Envoi refusé par la garde (pour les chemins qui lèvent plutôt que de renvoyer un message). */
export class RefusEnvoiIa extends Error {
  constructor(message: string) { super(message); this.name = 'RefusEnvoiIa' }
}

/** null = on peut envoyer ; sinon, le message (français) à montrer à l'utilisateur, et on N'ENVOIE PAS. */
export async function refusEnvoiIa(): Promise<string | null> {
  const verdict = await useIaDestinationStore.getState().verifierAvantEnvoi()
  const decision = decisionEnvoi(verdict, useIaDestinationStore.getState().destination)
  return decision.autorise ? null : decision.message
}
