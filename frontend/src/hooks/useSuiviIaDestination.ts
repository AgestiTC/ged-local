/**
 * useSuiviIaDestination — charge la destination de l'IA au montage de l'appli, puis la relit
 * périodiquement et au retour de focus de l'onglet : quand l'administrateur bascule sur GECO, les
 * autres utilisateurs voient le bandeau sans recharger la page. À monter UNE fois (MainLayout).
 *
 * La logique vit dans `demarrerSuiviIaDestination` (fonction ordinaire qui rend son nettoyage), pour être
 * testable sans rendu React. Les relectures « de confort » (focus, visibilité) respectent l'anti-rafale
 * du store (≥ 5 s entre deux) ; la minuterie, elle, relit toujours. Un changement de compte remet à zéro
 * la confirmation et le message d'erreur hérités de la session précédente, puis relit.
 */
import { useEffect } from 'react'
import { useIaDestinationStore } from '../stores/iaDestinationStore'
import { useAuthStore } from '../stores/authStore'

export const INTERVALLE_SUIVI_IA_MS = 45_000

export function demarrerSuiviIaDestination(): () => void {
  const store = () => useIaDestinationStore.getState()
  void store().charger()
  const minuterie = setInterval(() => { void store().charger() }, INTERVALLE_SUIVI_IA_MS)
  const auFocus = () => { void store().chargerSiPerime() }
  const auRetour = () => { if (document.visibilityState !== 'hidden') void store().chargerSiPerime() }
  window.addEventListener('focus', auFocus)
  document.addEventListener('visibilitychange', auRetour)
  // Changement de session (déconnexion / autre compte) : plus de fenêtre ni d'erreur héritées.
  let compte = identite()
  const desabonner = useAuthStore.subscribe(() => {
    const maintenant = identite()
    if (maintenant === compte) return
    compte = maintenant
    store().reinitialiserSession()
    void store().charger()
  })
  return () => {
    clearInterval(minuterie)
    window.removeEventListener('focus', auFocus)
    document.removeEventListener('visibilitychange', auRetour)
    desabonner()
  }
}

function identite(): string {
  const u = useAuthStore.getState().utilisateur
  const a = useAuthStore.getState()
  // Le rôle et la fin du chargement de /me comptent : un compte devenu non-admin repasse sur l'état fixe « local ».
  return `${a.charge ? 1 : 0}|${u ? `${u.id ?? ''}|${u.identifiant ?? ''}|${u.role}` : ''}|${a.authActive ? 1 : 0}`
}

export function useSuiviIaDestination(): void {
  useEffect(() => demarrerSuiviIaDestination(), [])
}
