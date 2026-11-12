/**
 * Tests — store du bouton « IA LOCAL / IA GECO »
 * ==============================================
 * Aucun appel réseau : `systemApi` est simulé. Principe vérifié : l'interface n'affirme jamais « local »
 * sans l'avoir lu, et aucun envoi interactif ne part sur un état périmé.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

const { iaDestination, basculerIa, updateConfig } = vi.hoisted(() => ({
  iaDestination: vi.fn(), basculerIa: vi.fn(), updateConfig: vi.fn(),
}))
vi.mock('../../api', () => ({ systemApi: { iaDestination, basculerIa, updateConfig } }))

import { useIaDestinationStore, reinitialiserIaDestination } from '../../stores/iaDestinationStore'
import { useAuthStore } from '../../stores/authStore'

const VIERGE = {
  destination: 'inconnu' as const, gecoModele: '', connu: false, chargement: false, erreur: null, erreurLecture: false,
  demande: null, enCours: false,
}
const etat = () => useIaDestinationStore.getState()
const LOCAL = { destination: 'local', geco_modele: 'geco/gros' }
const GECO = { destination: 'geco', geco_modele: 'geco/gros' }

/** Erreur HTTP façon axios : `response.data.detail`. */
const http = (detail: string) => ({ response: { status: 422, data: { detail } } })
/** Promesse pilotable à la main (pour les courses). */
function differee<T>() {
  let resoudre!: (v: T) => void
  const promesse = new Promise<T>(r => { resoudre = r })
  return { promesse, resoudre }
}

beforeEach(() => {
  iaDestination.mockReset(); basculerIa.mockReset(); updateConfig.mockReset()
  reinitialiserIaDestination()
  useIaDestinationStore.setState(VIERGE)
  useAuthStore.setState({ charge: true, authActive: false, utilisateur: null })   // auth éteinte = admin
})
afterEach(() => { vi.useRealTimers() })

const UTILISATEUR = { id: 'u1', identifiant: 'marie', nom: null, email: null, role: 'utilisateur' as const }

describe('rôle Utilisateur : fonction invisible, toujours local, AUCUN appel à la route', () => {
  beforeEach(() => useAuthStore.setState({ charge: true, authActive: true, utilisateur: UTILISATEUR }))

  it('charger : état fixe « local » confirmé, route jamais appelée', async () => {
    await etat().charger()
    expect(iaDestination).not.toHaveBeenCalled()
    expect(etat()).toMatchObject({ destination: 'local', gecoModele: '', connu: true, erreurLecture: false })
  })
  it('verifierAvantEnvoi : ok, route jamais appelée (envoi non bloqué)', async () => {
    expect(await etat().verifierAvantEnvoi()).toBe('ok')
    expect(iaDestination).not.toHaveBeenCalled()
  })
  it("même une réponse GECO qu'on lui aurait servie est ignorée : il reste local", async () => {
    iaDestination.mockResolvedValue(GECO)
    await etat().charger()
    expect(etat().destination).toBe('local')
  })
  it('demanderBascule : refus non_admin, aucune écriture', async () => {
    const d = await etat().demanderBascule({ admin: false })
    expect(d).toMatchObject({ ok: false, raison: 'non_admin' })
    expect(basculerIa).not.toHaveBeenCalled()
  })
})

describe('identité pas encore connue (/me non revenu)', () => {
  it('aucun appel, état « inconnu » conservé', async () => {
    useAuthStore.setState({ charge: false })
    await etat().charger()
    expect(iaDestination).not.toHaveBeenCalled()
    expect(etat().destination).toBe('inconnu')
  })
})

describe('trois états affichables', () => {
  it('au départ : inconnu (jamais « local » par défaut)', () => {
    expect(etat().destination).toBe('inconnu')
  })
  it('lecture réussie : local ou geco', async () => {
    iaDestination.mockResolvedValue(LOCAL)
    await etat().charger()
    expect(etat()).toMatchObject({ destination: 'local', connu: true })
    iaDestination.mockResolvedValue(GECO)
    await etat().charger()
    expect(etat()).toMatchObject({ destination: 'geco', gecoModele: 'geco/gros' })
  })
})

describe('charger', () => {
  it('erreur de lecture sans état antérieur : inconnu', async () => {
    iaDestination.mockRejectedValue(new Error('404'))
    await etat().charger()
    expect(etat()).toMatchObject({ destination: 'inconnu', connu: false, erreurLecture: true, chargement: false })
  })

  it('réponse hors contrat : échec de lecture (inconnu), PAS « local »', async () => {
    for (const hors of [{ destination: 'n_importe_quoi', geco_modele: '' }, { geco_modele: 'x' }, undefined, { destination: 'GECO' }]) {
      iaDestination.mockResolvedValue(hors)
      await etat().charger()
      expect(etat()).toMatchObject({ destination: 'inconnu', connu: false, erreurLecture: true, gecoModele: '' })
    }
  })

  it("une lecture en erreur ne masque PAS l'erreur d'une bascule déjà affichée", async () => {
    useIaDestinationStore.setState({ erreur: 'Refus du serveur' })
    iaDestination.mockRejectedValue(new Error('réseau'))
    await etat().charger()
    expect(etat().erreur).toBe('Refus du serveur')
  })

  it('lecture ratée APRÈS un état connu : dernier état gardé + erreurLecture (signe « non vérifié »)', async () => {
    iaDestination.mockResolvedValueOnce(GECO)
    await etat().charger()
    iaDestination.mockRejectedValueOnce(new Error('réseau'))
    await etat().charger()
    expect(etat()).toMatchObject({ destination: 'geco', gecoModele: 'geco/gros', erreurLecture: true })
    iaDestination.mockResolvedValueOnce(GECO)
    await etat().charger()
    expect(etat().erreurLecture).toBe(false)
  })

  it('réponse hors contrat APRÈS un état connu : état gardé, erreurLecture', async () => {
    iaDestination.mockResolvedValueOnce(LOCAL)
    await etat().charger()
    iaDestination.mockResolvedValueOnce({ destination: 'bizarre' })
    await etat().charger()
    expect(etat()).toMatchObject({ destination: 'local', erreurLecture: true })
  })
})

describe('courses', () => {
  it('une lecture partie AVANT une bascule est ignorée à son retour', async () => {
    useIaDestinationStore.setState({ destination: 'geco', gecoModele: 'geco/gros', connu: true })
    const vieille = differee<unknown>()
    iaDestination.mockReturnValueOnce(vieille.promesse)       // lecture ancienne, en vol
    const lecture = etat().charger()
    basculerIa.mockResolvedValue({})
    iaDestination.mockResolvedValueOnce({ destination: 'local', geco_modele: 'geco/gros' })   // relecture après bascule
    await etat().basculer('local')
    expect(etat().destination).toBe('local')
    vieille.resoudre(GECO)                                      // la vieille réponse « geco » arrive en retard
    await lecture
    expect(etat().destination).toBe('local')
  })

  it('après une bascule réussie : une relecture', async () => {
    useIaDestinationStore.setState({ destination: 'local', gecoModele: 'geco/gros', connu: true })
    basculerIa.mockResolvedValue({})
    iaDestination.mockResolvedValue(GECO)
    await etat().basculer('geco', { confirme: true, modele: 'geco/gros' })
    expect(iaDestination).toHaveBeenCalledTimes(1)
    expect(etat().destination).toBe('geco')
  })

  it('PUT en erreur ou réponse perdue (timeout) : relecture quand même, état réel affiché', async () => {
    useIaDestinationStore.setState({ destination: 'local', gecoModele: 'geco/gros', connu: true })
    basculerIa.mockRejectedValue(new Error('timeout'))     // le serveur a peut-être appliqué la bascule
    iaDestination.mockResolvedValue(GECO)
    const r = await etat().basculer('geco', { confirme: true, modele: 'geco/gros' })
    expect(r.ok).toBe(false)
    expect(iaDestination).toHaveBeenCalledTimes(1)
    expect(etat().destination).toBe('geco')                // la relecture dit la vérité : le bandeau apparaît
  })

  it('IA LOCAL toujours possible depuis un écran déjà « local » (arrêt d\'urgence sur écran périmé) : envoie le PUT', async () => {
    useIaDestinationStore.setState({ destination: 'local', connu: true })
    basculerIa.mockResolvedValue({})
    iaDestination.mockResolvedValue(LOCAL)
    const r = await etat().basculer('local')
    expect(basculerIa).toHaveBeenCalledWith('local')
    expect(r.ok).toBe(true)
  })

  it('avant la 1re lecture, « IA GECO » attend la lecture (pas de « aucun modèle choisi »)', async () => {
    iaDestination.mockResolvedValue(LOCAL)                 // la lecture apporte geco_modele
    const d = await etat().demanderBascule({ admin: true })
    expect(d.ok).toBe(true)
    expect(etat().demande).toEqual({ modele: 'geco/gros' })
  })

  it('avant la 1re lecture, lecture impossible : refus « inconnu », pas de fenêtre', async () => {
    iaDestination.mockRejectedValue(new Error('réseau'))
    const d = await etat().demanderBascule({ admin: true })
    expect(d).toMatchObject({ ok: false, raison: 'inconnu' })
    expect(etat().demande).toBeNull()
  })
})

describe('verifierAvantEnvoi', () => {
  it('ok : la destination relue est celle affichée', async () => {
    useIaDestinationStore.setState({ destination: 'local', connu: true })
    iaDestination.mockResolvedValue(LOCAL)
    expect(await etat().verifierAvantEnvoi()).toBe('ok')
  })
  it('change : elle diffère, l\'état est mis à jour (bandeau)', async () => {
    useIaDestinationStore.setState({ destination: 'local', connu: true })
    iaDestination.mockResolvedValue(GECO)
    expect(await etat().verifierAvantEnvoi()).toBe('change')
    expect(etat().destination).toBe('geco')
    iaDestination.mockResolvedValue(LOCAL)
    expect(await etat().verifierAvantEnvoi()).toBe('change')
    expect(etat().destination).toBe('local')
  })
  it('inconnu : la relecture échoue (erreur, hors contrat)', async () => {
    useIaDestinationStore.setState({ destination: 'local', connu: true })
    iaDestination.mockRejectedValue(new Error('réseau'))
    expect(await etat().verifierAvantEnvoi()).toBe('inconnu')
    iaDestination.mockResolvedValue({ destination: 'x' })
    expect(await etat().verifierAvantEnvoi()).toBe('inconnu')
  })
  it("inconnu : la relecture ne répond pas dans le délai (~5 s)", async () => {
    vi.useFakeTimers()
    useIaDestinationStore.setState({ destination: 'local', connu: true })
    iaDestination.mockReturnValue(new Promise(() => {}))
    const p = etat().verifierAvantEnvoi()
    await vi.advanceTimersByTimeAsync(5_100)
    expect(await p).toBe('inconnu')
  })
  it('FORCE toujours : ne se greffe pas sur une lecture ancienne en vol', async () => {
    useIaDestinationStore.setState({ destination: 'local', connu: true })
    const vieille = differee<unknown>()
    iaDestination.mockReturnValueOnce(vieille.promesse)
    void etat().charger()
    iaDestination.mockResolvedValueOnce(GECO)
    expect(await etat().verifierAvantEnvoi()).toBe('change')
    expect(iaDestination).toHaveBeenCalledTimes(2)
    vieille.resoudre(LOCAL)                                // la vieille réponse ne ré-écrase pas
    await Promise.resolve()
    expect(etat().destination).toBe('geco')
  })
})

describe('anti-rafale (focus)', () => {
  it('chargerSiPerime : pas deux lectures à moins de 5 s, mais charger() et verifierAvantEnvoi() passent toujours', async () => {
    iaDestination.mockResolvedValue(LOCAL)
    await etat().chargerSiPerime()
    await etat().chargerSiPerime()
    expect(iaDestination).toHaveBeenCalledTimes(1)
    await etat().charger()
    expect(iaDestination).toHaveBeenCalledTimes(2)
    await etat().verifierAvantEnvoi()
    expect(iaDestination).toHaveBeenCalledTimes(3)
  })
})

describe('bascule vers GECO', () => {
  beforeEach(() => useIaDestinationStore.setState({ destination: 'local', gecoModele: 'geco/gros', connu: true }))

  it("n'appelle PAS l'API sans confirmation", async () => {
    const r = await etat().basculer('geco')
    expect(basculerIa).not.toHaveBeenCalled()
    expect(r.ok).toBe(false)
    expect(etat().destination).toBe('local')
  })

  it("demanderBascule ouvre la confirmation sans appeler l'API d'écriture", async () => {
    const d = await etat().demanderBascule({ admin: true })
    expect(d.ok).toBe(true)
    expect(etat().demande).toEqual({ modele: 'geco/gros' })
    expect(basculerIa).not.toHaveBeenCalled()
  })

  it("un non-admin ne peut pas basculer : pas de confirmation, pas d'appel", async () => {
    const d = await etat().demanderBascule({ admin: false })
    expect(d).toMatchObject({ ok: false, raison: 'non_admin' })
    expect(etat().demande).toBeNull()
    expect(basculerIa).not.toHaveBeenCalled()
  })

  it('sans modèle GECO choisi : refus expliqué, pas de confirmation', async () => {
    useIaDestinationStore.setState({ gecoModele: '' })
    const d = await etat().demanderBascule({ admin: true })
    expect(d).toMatchObject({ ok: false, raison: 'modele_manquant' })
    expect(etat().demande).toBeNull()
  })

  it('liste GECO indisponible : refus expliqué', async () => {
    expect(await etat().demanderBascule({ admin: true, listeDisponible: false })).toMatchObject({ ok: false, raison: 'liste_indisponible' })
    expect(etat().demande).toBeNull()
  })

  it('annuler la confirmation : rien ne change, aucun appel', async () => {
    await etat().demanderBascule({ admin: true })
    etat().annulerBascule()
    expect(etat().demande).toBeNull()
    expect(basculerIa).not.toHaveBeenCalled()
    expect(etat().destination).toBe('local')
  })

  it('confirmée : envoie ia_destination ET geco_modele ensemble, puis passe sur GECO', async () => {
    basculerIa.mockResolvedValue({ ia_destination: 'geco' })
    iaDestination.mockResolvedValue(GECO)
    await etat().demanderBascule({ admin: true })
    const r = await etat().basculer('geco', { confirme: true, modele: 'geco/gros' })
    expect(basculerIa).toHaveBeenCalledWith('geco', 'geco/gros')
    expect(r.ok).toBe(true)
    expect(etat()).toMatchObject({ destination: 'geco', demande: null, erreur: null, enCours: false })
  })

  it('le modèle ANNONCÉ est celui qui est ENVOYÉ : s\'il a changé entre-temps, on rouvre sans envoyer', async () => {
    await etat().demanderBascule({ admin: true })                       // annonce geco/gros
    useIaDestinationStore.setState({ gecoModele: 'geco/autre' })         // l'admin (ou une relecture) change le modèle
    const r = await etat().basculer('geco', { confirme: true, modele: 'geco/gros' })
    expect(basculerIa).not.toHaveBeenCalled()
    expect(r.ok).toBe(false)
    expect(etat().demande).toEqual({ modele: 'geco/autre' })             // fenêtre rouverte avec le nouveau
    expect(etat().destination).toBe('local')
  })

  it('modèle annoncé devenu vide entre-temps : fenêtre fermée, rien envoyé', async () => {
    await etat().demanderBascule({ admin: true })
    useIaDestinationStore.setState({ gecoModele: '' })
    const r = await etat().basculer('geco', { confirme: true, modele: 'geco/gros' })
    expect(r.ok).toBe(false)
    expect(basculerIa).not.toHaveBeenCalled()
    expect(etat().demande).toBeNull()
  })

  it('pendant le PUT : `enCours` vrai (bouton occupé), faux ensuite', async () => {
    const put = differee<unknown>()
    basculerIa.mockReturnValue(put.promesse)
    iaDestination.mockResolvedValue(GECO)
    const p = etat().basculer('geco', { confirme: true, modele: 'geco/gros' })
    expect(etat().enCours).toBe(true)
    put.resoudre({})
    await p
    expect(etat().enCours).toBe(false)
  })

  it('refusée par le serveur (422) : état inchangé, message du serveur tel quel et PERSISTANT', async () => {
    basculerIa.mockRejectedValue(http('La liste des modèles GECO est indisponible.'))
    iaDestination.mockResolvedValue(LOCAL)
    await etat().demanderBascule({ admin: true })
    const r = await etat().basculer('geco', { confirme: true, modele: 'geco/gros' })
    expect(r).toEqual({ ok: false, message: 'La liste des modèles GECO est indisponible.' })
    expect(etat().destination).toBe('local')
    expect(etat().erreur).toBe('La liste des modèles GECO est indisponible.')
    expect(etat().demande).toBeNull()
    etat().effacerErreur()
    expect(etat().erreur).toBeNull()
  })

  it('403 « exige l\'authentification active et un compte administrateur » : rendu tel quel', async () => {
    const detail = 'Activer « IA GECO » exige l\'authentification active et un compte administrateur'
    basculerIa.mockRejectedValue({ response: { status: 403, data: { detail } } })
    iaDestination.mockResolvedValue(LOCAL)
    const r = await etat().basculer('geco', { confirme: true, modele: 'geco/gros' })
    expect(r).toEqual({ ok: false, message: detail })
    expect(etat().erreur).toBe(detail)
  })

  it('échec réseau sans detail : message générique, relecture', async () => {
    basculerIa.mockRejectedValue(new Error('Network Error'))
    iaDestination.mockResolvedValue(LOCAL)
    const r = await etat().basculer('geco', { confirme: true, modele: 'geco/gros' })
    expect(r.ok).toBe(false)
    expect(etat().destination).toBe('local')
    expect(etat().erreur).toBeTruthy()
  })

  it("confirmée mais sans modèle GECO : pas d'appel", async () => {
    useIaDestinationStore.setState({ gecoModele: '' })
    const r = await etat().basculer('geco', { confirme: true })
    expect(r.ok).toBe(false)
    expect(basculerIa).not.toHaveBeenCalled()
  })
})

describe('retour sur IA locale', () => {
  it('immédiat, sans confirmation, avec un message de succès', async () => {
    useIaDestinationStore.setState({ destination: 'geco', gecoModele: 'geco/gros', connu: true })
    basculerIa.mockResolvedValue({})
    iaDestination.mockResolvedValue(LOCAL)
    const r = await etat().basculer('local')
    expect(basculerIa).toHaveBeenCalledWith('local')
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.message).toMatch(/IA locale/)
    expect(etat().destination).toBe('local')
  })

  it('échec du retour : on reste sur GECO (le bandeau reste affiché) et on le dit', async () => {
    useIaDestinationStore.setState({ destination: 'geco', gecoModele: 'geco/gros', connu: true })
    basculerIa.mockRejectedValue(new Error('Network Error'))
    iaDestination.mockResolvedValue(GECO)
    const r = await etat().basculer('local')
    expect(r.ok).toBe(false)
    expect(etat().destination).toBe('geco')
    expect(etat().erreur).toBeTruthy()
  })
})

describe('définir le modèle GECO utilisé', () => {
  it('enregistre geco_modele seul, sans toucher à la destination', async () => {
    useIaDestinationStore.setState({ destination: 'local', connu: true })
    updateConfig.mockResolvedValue({})
    const r = await etat().definirGecoModele('geco/petit')
    expect(updateConfig).toHaveBeenCalledWith({ geco_modele: 'geco/petit' })
    expect(basculerIa).not.toHaveBeenCalled()
    expect(r.ok).toBe(true)
    expect(etat().gecoModele).toBe('geco/petit')
    expect(etat().destination).toBe('local')
  })
  it('refusé (422) : ancien modèle conservé, message du serveur', async () => {
    useIaDestinationStore.setState({ gecoModele: 'geco/gros' })
    updateConfig.mockRejectedValue(http("Ce modèle est un modèle d'embeddings."))
    const r = await etat().definirGecoModele('geco/emb')
    expect(r).toEqual({ ok: false, message: "Ce modèle est un modèle d'embeddings." })
    expect(etat().gecoModele).toBe('geco/gros')
    expect(etat().erreur).toBe("Ce modèle est un modèle d'embeddings.")
  })
})

describe('changement de session', () => {
  it('`demande` et `erreur` sont remises à zéro ; l\'état connu est conservé jusqu\'à la relecture', () => {
    useIaDestinationStore.setState({ demande: { modele: 'geco/x' }, erreur: 'vieux message', destination: 'geco', connu: true })
    etat().reinitialiserSession()
    expect(etat().demande).toBeNull()
    expect(etat().erreur).toBeNull()
  })
})
