/**
 * Tests — garde partagée avant envoi interactif (relecture de la destination puis décision).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

const { iaDestination } = vi.hoisted(() => ({ iaDestination: vi.fn() }))
vi.mock('../../api', () => ({ systemApi: { iaDestination } }))

import { useIaDestinationStore, reinitialiserIaDestination } from '../../stores/iaDestinationStore'
import { useAuthStore } from '../../stores/authStore'
import { refusEnvoiIa } from '../../utils/gardeEnvoiIa'
import { MSG_ENVOI_GECO_ACTIVE, MSG_ENVOI_INCONNU } from '../../utils/iaDestination'

beforeEach(() => {
  iaDestination.mockReset()
  useAuthStore.setState({ charge: true, authActive: false, utilisateur: null })
  reinitialiserIaDestination()
  useIaDestinationStore.setState({ destination: 'local', gecoModele: 'geco/x', connu: true, erreurLecture: false })
})

describe('refusEnvoiIa — rôle Utilisateur', () => {
  it('jamais bloqué, et aucun appel à la route de destination', async () => {
    useAuthStore.setState({ charge: true, authActive: true, utilisateur: { id: 'u', identifiant: 'm', nom: null, email: null, role: 'utilisateur' } })
    expect(await refusEnvoiIa()).toBeNull()
    expect(iaDestination).not.toHaveBeenCalled()
  })
})

describe('refusEnvoiIa', () => {
  it('ok : null, on envoie', async () => {
    iaDestination.mockResolvedValue({ destination: 'local', geco_modele: '' })
    expect(await refusEnvoiIa()).toBeNull()
  })
  it('devenu GECO : message, on N\'envoie PAS, et le bandeau apparaît (état mis à jour)', async () => {
    iaDestination.mockResolvedValue({ destination: 'geco', geco_modele: 'geco/x' })
    expect(await refusEnvoiIa()).toBe(MSG_ENVOI_GECO_ACTIVE)
    expect(useIaDestinationStore.getState().destination).toBe('geco')
  })
  it('devenu local (sens sûr) : on envoie', async () => {
    useIaDestinationStore.setState({ destination: 'geco' })
    iaDestination.mockResolvedValue({ destination: 'local', geco_modele: '' })
    expect(await refusEnvoiIa()).toBeNull()
    expect(useIaDestinationStore.getState().destination).toBe('local')
  })
  it('relecture impossible : message, on N\'envoie PAS', async () => {
    iaDestination.mockRejectedValue(new Error('réseau'))
    expect(await refusEnvoiIa()).toBe(MSG_ENVOI_INCONNU)
  })
})
