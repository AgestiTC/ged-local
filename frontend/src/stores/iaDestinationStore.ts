/**
 * Store « IA LOCAL / IA GECO » — Zustand (plan-liste-modeles, étape 5b)
 * ====================================================================
 * Réglage GLOBAL du serveur (`ia_destination`), lisible par tout utilisateur connecté, modifiable par
 * l'administrateur seul.
 *
 * Principe : l'interface n'affirme JAMAIS « local » sans l'avoir lu, et aucun envoi interactif ne part
 * sur un état périmé.
 *  - trois états affichables : `local` (lu), `geco`, `inconnu` (jamais lu, ou réponse hors contrat) ;
 *  - une lecture en échec APRÈS un état connu garde le dernier état mais lève `erreurLecture`
 *    (signe « non vérifié ») ;
 *  - `verifierAvantEnvoi` relit de force juste avant chaque envoi interactif ;
 *  - un compteur de génération (incrémenté par `basculer`) écarte les lectures parties avant une bascule,
 *    un numéro de séquence écarte les lectures dépassées par une plus récente ;
 *  - RÔLE UTILISATEUR : la fonction lui est invisible et ses demandes restent TOUJOURS locales (le serveur le
 *    garantit). Pour lui l'état est fixe « local », confirmé, SANS aucun appel à la route de destination ;
 *  - passer sur GECO exige une confirmation EXPLICITE et le modèle annoncé est celui qui est envoyé.
 */
import { create } from 'zustand'
import { systemApi } from '../api'
import { useAuthStore } from './authStore'
import { estAdmin } from '../utils/acces'
import {
  destinationValide, detailServeur, peutBasculerVersGeco,
  type DecisionBascule, type EtatIa, type IaDestination, type VerdictVerification,
} from '../utils/iaDestination'

export type ResultatBascule = { ok: true; message: string } | { ok: false; message: string }

export const DELAI_VERIFICATION_MS = 5_000   // plafond de la relecture avant envoi
export const ANTI_RAFALE_MS = 5_000          // écart minimal entre deux relectures « de confort » (focus)

interface IaDestinationState {
  destination: EtatIa
  gecoModele: string            // modèle GECO utilisé par « Auto » en mode GECO ('' = aucun choisi)
  connu: boolean                // une lecture CONFORME a réussi au moins une fois
  chargement: boolean
  erreur: string | null         // dernier échec de bascule / d'enregistrement (message du serveur), persistant
  erreurLecture: boolean        // la dernière lecture a échoué : l'état affiché n'est pas vérifié
  demande: { modele: string } | null   // confirmation de sortie internet en attente (modèle ANNONCÉ)
  enCours: boolean              // un PUT de bascule est en vol

  charger: () => Promise<void>
  chargerSiPerime: () => Promise<void>
  verifierAvantEnvoi: () => Promise<VerdictVerification>
  demanderBascule: (e: { admin: boolean; listeDisponible?: boolean }) => Promise<DecisionBascule>
  annulerBascule: () => void
  basculer: (vers: IaDestination, opts?: { confirme?: boolean; modele?: string }) => Promise<ResultatBascule>
  definirGecoModele: (modele: string) => Promise<ResultatBascule>
  effacerErreur: () => void
  reinitialiserSession: () => void
}

let chargementEnCours: Promise<void> | null = null
let generation = 0          // incrémenté par `basculer` : une lecture partie avant est ignorée
let sequence = 0            // numéro de la dernière lecture démarrée : seule celle-ci s'applique
let derniereLecture = 0     // horodatage de la dernière lecture démarrée (anti-rafale)

/** Remet à zéro l'état interne du module — tests. */
export function reinitialiserIaDestination(): void {
  chargementEnCours = null
  generation = 0
  sequence = 0
  derniereLecture = 0
}

export const useIaDestinationStore = create<IaDestinationState>()((set, get) => {
  /**
   * UNE lecture. Rend la destination lue (conforme) ou null (échec, hors contrat, ou dépassée).
   * L'état n'est modifié que si cette lecture est encore la plus récente et que aucune bascule n'a eu lieu depuis.
   */
  async function lire(): Promise<IaDestination | null> {
    // Non-administrateur : état fixe « local » (vrai pour lui), aucun appel réseau. Tant que l'identité n'est pas
    // connue (`/api/auth/me` pas encore revenu), on n'appelle rien non plus : l'état reste « inconnu ».
    const auth = useAuthStore.getState()
    if (!auth.charge) return null
    if (!estAdmin(auth)) {
      set({ destination: 'local', gecoModele: '', connu: true, erreurLecture: false })
      return 'local'
    }
    const g = generation
    const n = ++sequence
    derniereLecture = Date.now()
    let lue: IaDestination | null = null
    let geco = ''
    try {
      const r = await systemApi.iaDestination()
      lue = destinationValide(r?.destination)
      if (lue) geco = typeof r.geco_modele === 'string' ? r.geco_modele : ''
    } catch { lue = null }
    if (g !== generation || n !== sequence) return lue   // périmée : on ne touche pas à l'état
    if (lue) set({ destination: lue, gecoModele: geco, connu: true, erreurLecture: false })
    else set({ erreurLecture: true })                    // état antérieur gardé ; sinon il reste « inconnu »
    return lue
  }

  return {
    destination: 'inconnu',
    gecoModele: '',
    connu: false,
    chargement: false,
    erreur: null,
    erreurLecture: false,
    demande: null,
    enCours: false,

    charger: () => {
      if (chargementEnCours) return chargementEnCours   // un seul appel de confort à la fois
      set({ chargement: true })
      chargementEnCours = lire().then(() => undefined).finally(() => {
        set({ chargement: false })
        chargementEnCours = null
      })
      return chargementEnCours
    },

    chargerSiPerime: () => {
      if (Date.now() - derniereLecture < ANTI_RAFALE_MS && derniereLecture !== 0) return Promise.resolve()
      return get().charger()
    },

    verifierAvantEnvoi: async () => {
      // Non-administrateur : toujours local, jamais bloqué, aucun appel réseau.
      const auth = useAuthStore.getState()
      if (auth.charge && !estAdmin(auth)) { await lire(); return 'ok' }
      const affichee = get().destination
      // Relecture FORCÉE (jamais greffée sur une promesse ancienne), plafonnée à ~5 s.
      let minuterie: ReturnType<typeof setTimeout> | undefined
      const delai = new Promise<null>(resolve => { minuterie = setTimeout(() => resolve(null), DELAI_VERIFICATION_MS) })
      const lue = await Promise.race([lire(), delai])
      clearTimeout(minuterie)
      if (lue === null) return 'inconnu'
      return lue === affichee ? 'ok' : 'change'
    },

    demanderBascule: async ({ admin, listeDisponible }) => {
      // Avant la 1re lecture : on l'attend, au lieu de dire « aucun modèle choisi » sur un état vide.
      if (admin && !get().connu) await get().verifierAvantEnvoi()
      const { destination, gecoModele } = get()
      const decision = peutBasculerVersGeco({ admin, destination, gecoModele, listeDisponible })
      if (decision.ok) set({ demande: { modele: gecoModele }, erreur: null })
      return decision
    },

    annulerBascule: () => set({ demande: null }),

    basculer: async (vers, opts) => {
      if (vers === 'geco') {
        // Garde-fou : sans confirmation explicite, JAMAIS d'écriture.
        if (!opts?.confirme) return { ok: false, message: 'Confirmation requise avant de passer sur IA GECO.' }
        const modele = get().gecoModele
        if (!modele) {
          set({ demande: null })
          return { ok: false, message: "Aucun modèle GECO n'est choisi." }
        }
        // Le modèle ANNONCÉ doit être celui qui PART : s'il a changé depuis l'ouverture, on rouvre sans envoyer.
        if (opts.modele !== undefined && opts.modele !== modele) {
          set({ demande: { modele } })
          return { ok: false, message: `Le modèle GECO a changé (${modele}) : confirmez à nouveau.` }
        }
      }
      generation++
      set({ demande: null, enCours: true })
      let resultat: ResultatBascule
      try {
        const modele = get().gecoModele
        if (vers === 'geco') await systemApi.basculerIa('geco', modele)
        else await systemApi.basculerIa('local')
        set({ destination: vers, connu: true, erreur: null })
        resultat = vers === 'geco'
          ? { ok: true, message: `IA GECO activée (modèle ${modele}).` }
          : { ok: true, message: 'IA locale rétablie : plus aucune demande ne part chez GECO.' }
      } catch (e) {
        const message = detailServeur(e) ?? (vers === 'geco'
          ? "Bascule impossible : le serveur n'a pas répondu."
          : "Retour sur IA locale impossible : le serveur n'a pas répondu.")
        set({ erreur: message })
        resultat = { ok: false, message }
      }
      // Réponse refusée, perdue ou en timeout : le serveur a peut-être appliqué quand même → on relit toujours.
      await lire()
      set({ enCours: false })
      return resultat
    },

    definirGecoModele: async (modele) => {
      try {
        await systemApi.updateConfig({ geco_modele: modele })
        set({ gecoModele: modele, erreur: null })
        return { ok: true, message: modele ? `Modèle GECO utilisé : ${modele}.` : 'Aucun modèle GECO choisi.' }
      } catch (e) {
        const message = detailServeur(e) ?? "Enregistrement impossible : le serveur n'a pas répondu."
        set({ erreur: message })
        return { ok: false, message }
      }
    },

    effacerErreur: () => set({ erreur: null }),

    /** Changement de session (autre compte) : plus de confirmation ni de message hérités de la précédente. */
    reinitialiserSession: () => set({ demande: null, erreur: null, enCours: false }),
  }
})
