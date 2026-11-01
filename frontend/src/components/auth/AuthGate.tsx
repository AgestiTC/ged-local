/**
 * AuthGate — enveloppe de toute l'application (étape 3 du plan d'authentification).
 *  - charge `/api/auth/me` une fois au démarrage (le seul appel ajouté quand l'authentification est éteinte) ;
 *  - authentification éteinte : rend l'application TELLE QUELLE (aucun écran, aucun bandeau) ;
 *  - active sans session (ou après un 401) : écran « Se connecter » plein écran ;
 *  - accès de secours en cours : bandeau, application visible ;
 *  - 403 « réservé aux administrateurs » : un avis, une seule fois.
 * Le serveur reste la barrière : rien ici n'est une protection.
 */
import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { useShallow } from 'zustand/react/shallow'
import { useAuthStore } from '../../stores/authStore'
import { doitSeConnecter, suspensionActive } from '../../utils/acces'
import LoadingSpinner from '../common/LoadingSpinner'
import EcranConnexion from './EcranConnexion'

function heure(iso: string): string {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export default function AuthGate({ children }: { children: ReactNode }) {
  // Sélecteurs ciblés : un changement sans rapport du store ne refait pas le rendu de toute l'application.
  const s = useAuthStore(useShallow(st => ({
    charge: st.charge, authActive: st.authActive, utilisateur: st.utilisateur, nonConnecte: st.nonConnecte,
    suspensionJusqua: st.suspensionJusqua, refus403: st.refus403,
  })))
  const fermerRefus = useAuthStore(st => st.fermerRefus)

  useEffect(() => { void useAuthStore.getState().charger() }, [])

  if (!s.charge) {
    return <div className="flex items-center justify-center h-screen"><LoadingSpinner label="Chargement…" /></div>
  }
  if (doitSeConnecter(s)) return <EcranConnexion />

  return (
    <>
      {s.authActive && suspensionActive(s.suspensionJusqua) && s.suspensionJusqua && (
        <div role="status" className="bg-amber-100 text-amber-900 text-xs px-3 py-1.5 text-center border-b border-amber-300">
          Accès de secours en cours : l'authentification est suspendue jusqu'au {heure(s.suspensionJusqua)}.
          {!s.utilisateur && <> Vous n'êtes pas connecté.</>}
        </div>
      )}
      {s.refus403 && (
        <div role="alert" className="bg-red-50 text-red-800 text-sm px-3 py-2 flex items-center justify-center gap-3 border-b border-red-200">
          Cette action est réservée aux administrateurs.
          <button type="button" onClick={fermerRefus} aria-label="Fermer l'avis" className="p-0.5 hover:bg-red-100 rounded">
            <X size={14} />
          </button>
        </div>
      )}
      {children}
    </>
  )
}
