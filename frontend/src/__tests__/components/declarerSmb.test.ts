/**
 * Tests — Rangement › Déclarer depuis une Source NAS (étape 7) : le libellé proposé quand on n'en tape
 * pas. Le parcours à l'écran (source, partage, dossier, « Déclarer ce dossier ») est vérifié dans
 * l'appli, contre un serveur SMB jetable.
 */
import { describe, it, expect, vi } from 'vitest'

vi.mock('../../api', () => ({ sourcesApi: {}, extractApiError: () => '' }))
vi.mock('../../api/inventaire', () => ({ inventaireApi: {} }))

import { libelleParDefaut } from '../../components/rangement/DeclarerSmb'

describe('libellé proposé', () => {
  it('prend le dernier dossier choisi', () => {
    expect(libelleParDefaut('homes', '/Tom')).toBe('Tom')
    expect(libelleParDefaut('homes', '/Tom/Photos/')).toBe('Photos')
  })
  it('prend le nom du partage quand on déclare tout le partage', () => {
    expect(libelleParDefaut('media', '/')).toBe('media')
    expect(libelleParDefaut('media', '')).toBe('media')
  })
})
