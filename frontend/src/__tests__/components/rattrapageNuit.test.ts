import { describe, expect, it } from 'vitest'
import { libelleDernier } from '../../components/settings/RattrapageNuit'

describe('libelleDernier (rattrapage de nuit)', () => {
  it('aucun passage', () => {
    expect(libelleDernier(null)).toBe("Aucun passage pour l'instant.")
    expect(libelleDernier({ heure: '02:00', plafond: 100, dernier: null })).toBe("Aucun passage pour l'instant.")
  })

  it('passage terminé : le bilan par volet', () => {
    const t = libelleDernier({ heure: '02:00', plafond: 100, dernier: {
      date: '2026-11-19T01:00:30Z', statut: 'completed', erreur: null,
      resultat: { erreurs: 3, analyse_ia: 1, vecteurs: 100, total: 104, plafond: 100 } } })
    expect(t).toContain('3 erreur(s), 1 analyse(s) IA, 100 document(s) sans vecteurs remis en file')
  })

  it('passage en échec : le statut, sans bilan', () => {
    const t = libelleDernier({ heure: '02:00', plafond: 100, dernier: {
      date: '2026-11-19T01:00:30Z', statut: 'failed', erreur: 'boom', resultat: null } })
    expect(t).toMatch(/\(en échec\)\.$/)
  })
})
