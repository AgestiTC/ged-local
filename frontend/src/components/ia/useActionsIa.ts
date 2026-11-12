/**
 * useActionsIa — LES deux gestes du bouton « IA LOCAL / IA GECO », partagés par l'en-tête, le
 * bandeau, les Paramètres et la proposition de repli du chat : un seul code, une seule confirmation.
 */
import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useIaDestinationStore } from '../../stores/iaDestinationStore'
import { useAuthStore } from '../../stores/authStore'
import { estAdmin } from '../../utils/acces'
import { useToast } from '../common/Toast'

export function useActionsIa() {
  const toast = useToast()
  const navigate = useNavigate()

  /** Ouvre la confirmation ; si elle est impossible, explique et renvoie vers les Paramètres. */
  const versGeco = useCallback(async (listeDisponible?: boolean) => {
    // Avant la 1re lecture, le store attend la lecture (au lieu de répondre « aucun modèle choisi »).
    const decision = await useIaDestinationStore.getState().demanderBascule({
      admin: estAdmin(useAuthStore.getState()), listeDisponible,
    })
    if (decision.ok) return
    toast.error(decision.message)
    if (decision.raison === 'modele_manquant' || decision.raison === 'liste_indisponible') navigate('/settings')
  }, [toast, navigate])

  /** Retour immédiat sur IA locale, sans confirmation. */
  const versLocal = useCallback(async () => {
    const r = await useIaDestinationStore.getState().basculer('local')
    if (r.ok) toast.success(r.message)
    else toast.error(r.message)
  }, [toast])

  return { versGeco, versLocal }
}
