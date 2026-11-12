/**
 * Tests — suivi périodique de la destination de l'IA (minuterie, focus, nettoyage, session).
 * Faux minuteurs de vitest ; `systemApi` simulé.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

const { iaDestination } = vi.hoisted(() => ({ iaDestination: vi.fn() }))
vi.mock('../../api', () => ({ systemApi: { iaDestination }, authApi: { me: vi.fn() } }))

import { useIaDestinationStore, reinitialiserIaDestination } from '../../stores/iaDestinationStore'
import { useAuthStore } from '../../stores/authStore'
import { demarrerSuiviIaDestination, INTERVALLE_SUIVI_IA_MS } from '../../hooks/useSuiviIaDestination'

beforeEach(() => {
  vi.useFakeTimers()
  iaDestination.mockReset()
  iaDestination.mockResolvedValue({ destination: 'local', geco_modele: '' })
  reinitialiserIaDestination()
  useIaDestinationStore.setState({ destination: 'inconnu', gecoModele: '', connu: false, erreur: null, demande: null, erreurLecture: false })
  useAuthStore.setState({ charge: true, authActive: false, utilisateur: null })
})
afterEach(() => { vi.useRealTimers() })

describe('demarrerSuiviIaDestination', () => {
  it('charge au démarrage', async () => {
    const arret = demarrerSuiviIaDestination()
    await vi.advanceTimersByTimeAsync(0)
    expect(iaDestination).toHaveBeenCalledTimes(1)
    expect(useIaDestinationStore.getState().destination).toBe('local')
    arret()
  })

  it('relit à chaque intervalle', async () => {
    const arret = demarrerSuiviIaDestination()
    await vi.advanceTimersByTimeAsync(INTERVALLE_SUIVI_IA_MS)
    expect(iaDestination).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(INTERVALLE_SUIVI_IA_MS)
    expect(iaDestination).toHaveBeenCalledTimes(3)
    arret()
  })

  it('relit au retour de focus, mais pas en rafale (≥ 5 s entre deux)', async () => {
    const arret = demarrerSuiviIaDestination()
    await vi.advanceTimersByTimeAsync(0)
    window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(0)
    expect(iaDestination).toHaveBeenCalledTimes(1)           // trop tôt après la lecture initiale
    await vi.advanceTimersByTimeAsync(6_000)
    window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(0)
    expect(iaDestination).toHaveBeenCalledTimes(2)
    arret()
  })

  it('relit au retour de visibilité de l\'onglet', async () => {
    const arret = demarrerSuiviIaDestination()
    await vi.advanceTimersByTimeAsync(6_000)
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(0)
    expect(iaDestination).toHaveBeenCalledTimes(2)
    arret()
  })

  it('nettoyage au démontage : plus de minuterie ni d\'écouteur', async () => {
    const arret = demarrerSuiviIaDestination()
    await vi.advanceTimersByTimeAsync(0)
    arret()
    iaDestination.mockClear()
    await vi.advanceTimersByTimeAsync(INTERVALLE_SUIVI_IA_MS * 3)
    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(0)
    expect(iaDestination).not.toHaveBeenCalled()
  })

  it('rôle Utilisateur : aucune lecture de la route (ni démarrage, ni minuterie, ni focus)', async () => {
    useAuthStore.setState({ charge: true, authActive: true, utilisateur: { id: 'u9', identifiant: 'm', nom: null, email: null, role: 'utilisateur' } })
    const arret = demarrerSuiviIaDestination()
    await vi.advanceTimersByTimeAsync(INTERVALLE_SUIVI_IA_MS * 2)
    window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(0)
    expect(iaDestination).not.toHaveBeenCalled()
    expect(useIaDestinationStore.getState().destination).toBe('local')
    arret()
  })

  it('changement de compte : confirmation et erreur héritées remises à zéro, puis relecture', async () => {
    const arret = demarrerSuiviIaDestination()
    await vi.advanceTimersByTimeAsync(0)
    useIaDestinationStore.setState({ demande: { modele: 'geco/x' }, erreur: 'message du compte précédent' })
    iaDestination.mockClear()
    useAuthStore.setState({ utilisateur: { id: 'u2', identifiant: 'autre', nom: null, email: null, role: 'utilisateur' } })
    await vi.advanceTimersByTimeAsync(0)
    const s = useIaDestinationStore.getState()
    expect(s.demande).toBeNull()
    expect(s.erreur).toBeNull()
    expect(iaDestination).toHaveBeenCalledTimes(1)
    arret()
  })
})
