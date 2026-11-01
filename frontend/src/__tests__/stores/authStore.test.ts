/**
 * Tests — authStore + intercepteurs 401/403 des clients axios
 * ===========================================================
 * Aucun appel réseau : `authApi` est simulé, et les clients axios reçoivent un adaptateur factice.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios'

const { me, logout } = vi.hoisted(() => ({ me: vi.fn(), logout: vi.fn() }))
vi.mock('../../api', () => ({ authApi: { me, logout } }))

import { apiClient, apiClientLong, DETAIL_ADMIN_SEULEMENT } from '../../api/client'
import { useAuthStore, reinitialiserAuth } from '../../stores/authStore'
import { doitSeConnecter } from '../../utils/acces'

const VIERGE = {
  charge: false, connu: false, authActive: false, utilisateur: null, adresseConnexion: null, wikiUrl: null,
  suspensionJusqua: null, nonConnecte: false, sessionExpiree: false, refus403: false, refus403Montre: false,
  derniereVerif: 0,
}
const futur = () => new Date(Date.now() + 3_600_000).toISOString()
const ETEINT = { auth_active: false, adresse_connexion: null, wiki_url: null, utilisateur: null }
const ACTIF_SANS_SESSION = { auth_active: true, adresse_connexion: null, wiki_url: null, utilisateur: null }
const UTILISATEUR = { identifiant: 'ml-test', nom: 'Marie Fictive', email: null, role: 'utilisateur' as const }
const CONNECTE = { charge: true, connu: true, authActive: true, utilisateur: UTILISATEUR }

function adaptateur(status: number, detail?: string): AxiosAdapter {
  return (config: InternalAxiosRequestConfig) => Promise.reject(new AxiosError(
    'echec', String(status), config, null,
    { status, statusText: '', headers: {}, config, data: detail ? { detail } : {} }))
}

beforeEach(() => {
  me.mockReset(); logout.mockReset()
  me.mockResolvedValue(ETEINT)   // par défaut /me répond « éteint » : un recontrôle déclenché par un 401 ne plante pas
  reinitialiserAuth()
  useAuthStore.setState(VIERGE)
  vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => { reinitialiserAuth(); vi.useRealTimers() })

describe('charger', () => {
  it('éteinte : aucune connexion demandée', async () => {
    await useAuthStore.getState().charger()
    const s = useAuthStore.getState()
    expect(s.charge).toBe(true)
    expect(s.connu).toBe(true)
    expect(s.authActive).toBe(false)
    expect(s.utilisateur).toBeNull()
  })

  it('active et connecté : la personne, l\'adresse de connexion et le lien du wiki sont retenus', async () => {
    me.mockResolvedValue({ auth_active: true, adresse_connexion: 'https://ged.test.invalid',
      wiki_url: 'https://wiki.test.invalid/', utilisateur: { ...UTILISATEUR, id: 'id-fictif' } })
    await useAuthStore.getState().charger()
    const s = useAuthStore.getState()
    expect(s.utilisateur).toMatchObject({ ...UTILISATEUR, id: 'id-fictif' })
    expect(s.adresseConnexion).toBe('https://ged.test.invalid')
    expect(s.wikiUrl).toBe('https://wiki.test.invalid/')
    expect(s.nonConnecte).toBe(false)
  })

  it('suspension de secours : échéance retenue', async () => {
    me.mockResolvedValue({ ...ACTIF_SANS_SESSION, suspension_jusqua: '2030-01-01T10:00:00+00:00' })
    await useAuthStore.getState().charger()
    expect(useAuthStore.getState().suspensionJusqua).toBe('2030-01-01T10:00:00+00:00')
  })

  it('un 401 antérieur est levé si /me dit que la session est bonne', async () => {
    useAuthStore.setState({ nonConnecte: true })
    me.mockResolvedValue({ ...ACTIF_SANS_SESSION, utilisateur: UTILISATEUR })
    await useAuthStore.getState().charger()
    expect(useAuthStore.getState().nonConnecte).toBe(false)
  })

  it('/me injoignable : on rend la main (charge = true), l\'état reste INCONNU et non « éteint »', async () => {
    vi.useFakeTimers()
    me.mockRejectedValue(new Error('réseau'))
    await useAuthStore.getState().charger()
    const s = useAuthStore.getState()
    expect(s.charge).toBe(true)
    expect(s.connu).toBe(false)
    expect(s.authActive).toBe(false)
  })

  it('un seul /me à la fois', async () => {
    await Promise.all([useAuthStore.getState().charger(), useAuthStore.getState().charger()])
    expect(me).toHaveBeenCalledTimes(1)
  })

  it('arrivée sans session : pas de « session expirée », l\'écran de connexion est requis', async () => {
    me.mockResolvedValue(ACTIF_SANS_SESSION)
    await useAuthStore.getState().charger()
    expect(useAuthStore.getState().sessionExpiree).toBe(false)
    expect(doitSeConnecter(useAuthStore.getState())).toBe(true)
  })
})

describe('intercepteur 401', () => {
  it.each([['apiClient', apiClient], ['apiClientLong', apiClientLong]])(
    '%s : bascule « non connecté » quand l\'authentification est active', async (_n, client) => {
      useAuthStore.setState(CONNECTE)
      await expect(client.get('/documents', { adapter: adaptateur(401, 'Authentification requise') })).rejects.toBeTruthy()
      expect(useAuthStore.getState().nonConnecte).toBe(true)
    })

  it('éteinte : un 401 isolé ne verrouille jamais l\'interface', async () => {
    useAuthStore.setState({ charge: true, connu: true, authActive: false })
    await expect(apiClient.get('/x', { adapter: adaptateur(401) })).rejects.toBeTruthy()
    expect(useAuthStore.getState().nonConnecte).toBe(false)
    expect(doitSeConnecter(useAuthStore.getState())).toBe(false)
  })

  it('rafale de 401 : un seul état, aucun avis empilé, pas de /me en boucle', async () => {
    useAuthStore.setState(CONNECTE)
    await Promise.allSettled(Array.from({ length: 20 }, () => apiClient.get('/x', { adapter: adaptateur(401) })))
    const s = useAuthStore.getState()
    expect(s.nonConnecte).toBe(true)
    expect(s.refus403).toBe(false)
    expect(me).not.toHaveBeenCalled()
  })

  it('avant la fin du /me : /me tranche (éteint = jamais verrouillé)', async () => {
    useAuthStore.setState({ charge: false })
    await expect(apiClient.get('/x', { adapter: adaptateur(401) })).rejects.toBeTruthy()
    await useAuthStore.getState().charger()
    expect(useAuthStore.getState().nonConnecte).toBe(false)
    expect(doitSeConnecter(useAuthStore.getState())).toBe(false)
  })

  it('personne connectée puis 401 : « session expirée » est retenu', async () => {
    useAuthStore.setState(CONNECTE)
    await expect(apiClient.get('/x', { adapter: adaptateur(401) })).rejects.toBeTruthy()
    expect(useAuthStore.getState().sessionExpiree).toBe(true)
  })

  it('la requête échoue toujours pour l\'appelant (l\'erreur est relancée)', async () => {
    useAuthStore.setState(CONNECTE)
    await expect(apiClient.get('/x', { adapter: adaptateur(401) })).rejects.toMatchObject({ response: { status: 401 } })
  })
})

describe('accès de secours (suspension)', () => {
  it('un 401 (ex. liste des personnes) ne verrouille PAS l\'application pendant la suspension', async () => {
    useAuthStore.setState({ ...CONNECTE, utilisateur: null, suspensionJusqua: futur() })
    await expect(apiClient.get('/auth/utilisateurs', { adapter: adaptateur(401) })).rejects.toBeTruthy()
    const s = useAuthStore.getState()
    expect(s.nonConnecte).toBe(false)
    expect(doitSeConnecter(s)).toBe(false)
  })

  it('suspension échue : un 401 verrouille de nouveau', async () => {
    useAuthStore.setState({ ...CONNECTE, utilisateur: null, suspensionJusqua: new Date(Date.now() - 1000).toISOString() })
    await expect(apiClient.get('/x', { adapter: adaptateur(401) })).rejects.toBeTruthy()
    expect(doitSeConnecter(useAuthStore.getState())).toBe(true)
  })
})

describe('/me en échec ou auth activée après coup', () => {
  it('/me échoue puis un 401 relance /me, qui fait basculer l\'appli si l\'auth est active', async () => {
    vi.useFakeTimers()
    me.mockRejectedValueOnce(new Error('502'))
    await useAuthStore.getState().charger()
    expect(useAuthStore.getState().connu).toBe(false)
    vi.setSystemTime(Date.now() + 11_000)
    me.mockResolvedValue(ACTIF_SANS_SESSION)
    await expect(apiClient.get('/x', { adapter: adaptateur(401) })).rejects.toBeTruthy()
    await vi.advanceTimersByTimeAsync(0)
    const s = useAuthStore.getState()
    expect(s.connu).toBe(true)
    expect(doitSeConnecter(s)).toBe(true)
  })

  it('éteinte au chargement puis activée : le 401 suivant relance /me', async () => {
    vi.useFakeTimers()
    await useAuthStore.getState().charger()
    expect(doitSeConnecter(useAuthStore.getState())).toBe(false)
    me.mockResolvedValue(ACTIF_SANS_SESSION)
    vi.setSystemTime(Date.now() + 11_000)
    await expect(apiClient.get('/x', { adapter: adaptateur(401) })).rejects.toBeTruthy()
    await vi.advanceTimersByTimeAsync(0)
    expect(doitSeConnecter(useAuthStore.getState())).toBe(true)
  })

  it('tant que l\'auth est éteinte : jamais verrouillé ; rafale de 401 = un seul /me par fenêtre', async () => {
    vi.useFakeTimers()
    await useAuthStore.getState().charger()
    me.mockClear()
    vi.setSystemTime(Date.now() + 11_000)
    await Promise.allSettled(Array.from({ length: 15 }, () => apiClient.get('/x', { adapter: adaptateur(401) })))
    await vi.advanceTimersByTimeAsync(0)
    expect(me).toHaveBeenCalledTimes(1)
    expect(doitSeConnecter(useAuthStore.getState())).toBe(false)
    vi.setSystemTime(Date.now() + 3_000)   // encore dans la fenêtre : pas de /me de plus
    await expect(apiClient.get('/x', { adapter: adaptateur(401) })).rejects.toBeTruthy()
    expect(me).toHaveBeenCalledTimes(1)
  })

  it('relance en arrière-plan avec backoff plafonné tant que /me échoue, puis s\'arrête', async () => {
    vi.useFakeTimers()
    me.mockRejectedValue(new Error('502'))
    await useAuthStore.getState().charger()
    expect(me).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1_999); expect(me).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1); expect(me).toHaveBeenCalledTimes(2)         // +2 s
    await vi.advanceTimersByTimeAsync(5_000); expect(me).toHaveBeenCalledTimes(3)      // +5 s
    await vi.advanceTimersByTimeAsync(10_000); expect(me).toHaveBeenCalledTimes(4)     // +10 s
    for (let i = 0; i < 4; i++) await vi.advanceTimersByTimeAsync(30_000)
    expect(me.mock.calls.length).toBeLessThanOrEqual(9)                                 // plafonné : pas de rafale
    me.mockResolvedValue(ETEINT)
    await vi.advanceTimersByTimeAsync(30_000)
    const n = me.mock.calls.length
    await vi.advanceTimersByTimeAsync(120_000)
    expect(me).toHaveBeenCalledTimes(n)                                                 // succès : plus de relance
    expect(useAuthStore.getState().connu).toBe(true)
  })
})

describe('intercepteur 403', () => {
  it('« réservé aux administrateurs » : avis affiché UNE fois', async () => {
    for (let i = 0; i < 5; i++) {
      await expect(apiClient.get('/system/config', { adapter: adaptateur(403, DETAIL_ADMIN_SEULEMENT) })).rejects.toBeTruthy()
    }
    expect(useAuthStore.getState().refus403).toBe(true)
    useAuthStore.getState().fermerRefus()
    expect(useAuthStore.getState().refus403).toBe(false)
    await expect(apiClientLong.get('/system/config', { adapter: adaptateur(403, DETAIL_ADMIN_SEULEMENT) })).rejects.toBeTruthy()
    expect(useAuthStore.getState().refus403).toBe(false)   // déjà montré une fois : on ne harcèle pas
  })

  it('un autre 403 (origine refusée…) n\'est pas présenté comme un droit manquant', async () => {
    await expect(apiClient.put('/x', {}, { adapter: adaptateur(403, 'Origine de la requête non autorisée') })).rejects.toBeTruthy()
    expect(useAuthStore.getState().refus403).toBe(false)
  })

  it('un 403 ne déclenche pas l\'écran de connexion', async () => {
    useAuthStore.setState(CONNECTE)
    await expect(apiClient.get('/x', { adapter: adaptateur(403, DETAIL_ADMIN_SEULEMENT) })).rejects.toBeTruthy()
    expect(useAuthStore.getState().nonConnecte).toBe(false)
  })
})

describe('deconnecter', () => {
  it('POST logout puis navigation vers l\'accueil', async () => {
    logout.mockResolvedValue({ deconnecte: true, end_session_endpoint: null })
    const aller = vi.fn()
    await useAuthStore.getState().deconnecter(aller)
    expect(logout).toHaveBeenCalledTimes(1)
    expect(aller).toHaveBeenCalledWith('/')
  })

  it('va clore la session côté SSO si l\'adresse est en https', async () => {
    logout.mockResolvedValue({ deconnecte: true, end_session_endpoint: 'https://sso.test.invalid/logout' })
    const aller = vi.fn()
    await useAuthStore.getState().deconnecter(aller)
    expect(aller).toHaveBeenCalledWith('https://sso.test.invalid/logout')
  })

  it.each(['http://sso.test.invalid/logout', 'javascript:alert(1)'])(
    'ignore un end_session_endpoint non https (%s)', async (fin) => {
      logout.mockResolvedValue({ deconnecte: true, end_session_endpoint: fin })
      const aller = vi.fn()
      await useAuthStore.getState().deconnecter(aller)
      expect(aller).toHaveBeenCalledWith('/')
    })

  it('même si le POST échoue, on recharge l\'accueil', async () => {
    logout.mockRejectedValue(new Error('réseau'))
    const aller = vi.fn()
    await useAuthStore.getState().deconnecter(aller)
    expect(aller).toHaveBeenCalledWith('/')
  })
})
