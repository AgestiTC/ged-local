/**
 * Tests — Rangement › Plan de classement : quels emplacements l'onglet propose, et quel partage ils suivent.
 * Régression du 16/11/2026 : après la bascule SMB, l'onglet affichait « Aucun emplacement du NAS ».
 */
import { describe, it, expect, vi } from 'vitest'

vi.mock('../../api', () => ({ extractApiError: () => '' }))
vi.mock('../../api/inventaire', () => ({ inventaireApi: {}, planApi: {} }))
vi.mock('../../components/common/Toast', () => ({ useToast: () => ({}) }))
vi.mock('../../components/common/Confirmation', () => ({ confirmerTexte: vi.fn(), saisirTexte: vi.fn() }))

import { emplacementsDuPlan, partageDe } from '../../components/rangement/PlanClassement'
import type { EmplacementInventaire } from '../../api/inventaire'

const emp = (o: Partial<EmplacementInventaire>) => ({ id: 1, libelle: 'x', racine: '', source: 'serveur', actif: true, ...o }) as EmplacementInventaire

describe('emplacements du plan', () => {
  it('garde les emplacements SMB (cas réel après la bascule)', () => {
    const liste = [
      emp({ id: 1, source: 'smb', racine: 'smb://192.168.42.200/media', partage: 'media' }),
      emp({ id: 2, source: 'smb', racine: 'smb://192.168.42.200/media/nas-media', partage: 'media' }),
      emp({ id: 3, source: 'smb', racine: 'smb://192.168.42.200/homes/Tom', partage: 'homes' }),
      emp({ id: 4, source: 'agent', racine: 'C:/Users' }),
      emp({ id: 5, source: 'smb', partage: 'media', actif: false }),
    ]
    expect(emplacementsDuPlan(liste).map(e => e.id)).toEqual([1, 2, 3])
  })
  it('SMB : le partage vient du champ, pas de la fin de la racine', () => {
    expect(partageDe(emp({ source: 'smb', racine: 'smb://192.168.42.200/media/nas-media', partage: 'media' }))).toBe('media')
    expect(partageDe(emp({ source: 'serveur', racine: '/mnt/media/' }))).toBe('media')
  })
})
