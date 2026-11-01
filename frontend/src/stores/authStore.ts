/**
 * Store Authentification — état de connexion (plan d'authentification, étape 3)
 * ============================================================================
 * Chargé au démarrage par UN `GET /api/auth/me` (le seul appel ajouté quand l'authentification est
 * éteinte). Ce store ne décide d'aucun droit : le serveur reste la barrière, ici on n'affiche que
 * l'écran de connexion, le nom de la personne et les avis « réservé aux administrateurs ».
 *
 * « Inconnu » ≠ « éteint » : tant que `/me` n'a jamais répondu (`connu = false`, ex. 502 au redémarrage),
 * on rend la main à l'interface mais on RELANCE `/me` en arrière-plan (backoff plafonné) ; et un 401
 * reçu alors que l'authentification n'est pas connue comme active relance `/me` (anti-rebond ~10 s) —
 * ce qui couvre aussi l'authentification activée alors que l'onglet était déjà ouvert.
 *
 * Intercepteurs des clients axios (api/client.ts) :
 *   - 401 → si l'authentification est connue active : `nonConnecte = true` et l'écran « Se connecter »
 *     prend la main (état booléen : une rafale de 401 ne produit ni boucle ni avis en rafale). Pendant un
 *     accès de secours (suspension), un 401 ne verrouille rien : le serveur laisse tout passer.
 *   - 403 « réservé aux administrateurs » → un avis, UNE seule fois par chargement de page.
 */
import { create } from 'zustand'
import { authApi } from '../api'
import { definirGestionnairesAuth } from '../api/client'
import { finSessionSure, suspensionActive, type AuthUtilisateur } from '../utils/acces'

const ANTI_REBOND_MS = 10_000
const DELAIS_RELANCE_MS = [2_000, 5_000, 10_000, 30_000]   // le dernier se répète : jamais de rafale

interface AuthState {
  charge: boolean                       // `/me` a répondu (ou échoué) : on peut afficher l'application
  connu: boolean                        // `/me` a RÉPONDU au moins une fois (sinon l'état est inconnu, pas « éteint »)
  authActive: boolean
  utilisateur: AuthUtilisateur | null
  adresseConnexion: string | null
  wikiUrl: string | null                // simple lien du wiki (menu), lisible par tous les rôles
  suspensionJusqua: string | null       // accès de secours en cours
  nonConnecte: boolean                  // un 401 a été vu alors que l'authentification est active
  sessionExpiree: boolean               // ce 401 est tombé alors qu'une personne était connectée
  refus403: boolean                     // avis « réservé aux administrateurs » à l'écran
  refus403Montre: boolean               // déjà montré une fois : on ne harcèle pas
  derniereVerif: number                 // dernier lancement de /me (ms) : anti-rebond

  charger: () => Promise<void>
  sur401: () => void
  sur403Admin: () => void
  fermerRefus: () => void
  /** POST logout puis navigation (accueil, ou fin de session SSO si son adresse est en https). */
  deconnecter: (aller?: (url: string) => void) => Promise<void>
}

let chargementEnCours: Promise<void> | null = null
let minuterie: ReturnType<typeof setTimeout> | null = null
let echecs = 0

/** Remet à zéro l'état interne du module (relances, chargement en cours) — tests. */
export function reinitialiserAuth(): void {
  if (minuterie) clearTimeout(minuterie)
  minuterie = null
  chargementEnCours = null
  echecs = 0
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  charge: false,
  connu: false,
  authActive: false,
  utilisateur: null,
  adresseConnexion: null,
  wikiUrl: null,
  suspensionJusqua: null,
  nonConnecte: false,
  sessionExpiree: false,
  refus403: false,
  refus403Montre: false,
  derniereVerif: 0,

  charger: () => {
    if (chargementEnCours) return chargementEnCours
    set({ derniereVerif: Date.now() })
    chargementEnCours = (async () => {
      try {
        const e = await authApi.me()
        echecs = 0
        set({
          charge: true,
          connu: true,
          authActive: !!e.auth_active,
          utilisateur: e.utilisateur ?? null,
          adresseConnexion: e.adresse_connexion ?? null,
          wikiUrl: e.wiki_url ?? null,
          suspensionJusqua: e.suspension_jusqua ?? null,
          nonConnecte: false,   // `/me` fait foi : un 401 antérieur est levé si la session est bonne
          sessionExpiree: false,
        })
      } catch {
        // `/me` n'échoue jamais côté serveur : s'il ne répond pas, le backend est injoignable (redémarrage,
        // réseau). On rend la main sans inventer d'état, et on réessaie en arrière-plan.
        set({ charge: true })
        const delai = DELAIS_RELANCE_MS[Math.min(echecs, DELAIS_RELANCE_MS.length - 1)]
        echecs += 1
        if (minuterie) clearTimeout(minuterie)
        minuterie = setTimeout(() => { minuterie = null; void get().charger() }, delai)
      } finally {
        chargementEnCours = null
      }
    })()
    return chargementEnCours
  },

  sur401: () => {
    const s = get()
    if (suspensionActive(s.suspensionJusqua)) return   // secours : un 401 isolé n'est pas une déconnexion
    if (!(s.connu && s.authActive)) {
      // Authentification éteinte ou inconnue : on ne verrouille JAMAIS sur un 401, mais on revérifie
      // (elle a pu être activée, ou `/me` avoir échoué) — au plus une fois par fenêtre d'anti-rebond.
      if (Date.now() - s.derniereVerif >= ANTI_REBOND_MS) void get().charger()
      return
    }
    if (!s.nonConnecte) set({ nonConnecte: true, sessionExpiree: s.utilisateur !== null })
  },

  sur403Admin: () => {
    if (get().refus403Montre) return
    set({ refus403: true, refus403Montre: true })
  },

  fermerRefus: () => set({ refus403: false }),

  deconnecter: async (aller = (url: string) => window.location.assign(url)) => {
    let destination = '/'
    try {
      const r = await authApi.logout()
      destination = finSessionSure(r.end_session_endpoint) ?? '/'
    } catch { /* même en cas d'échec : on recharge l'accueil, la session est jugée par le serveur */ }
    aller(destination)
  },
}))

definirGestionnairesAuth({
  sur401: () => useAuthStore.getState().sur401(),
  sur403Admin: () => useAuthStore.getState().sur403Admin(),
})
