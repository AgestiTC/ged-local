import { describe, expect, it } from 'vitest'
import { bilanSimulation } from '../../components/settings/CategoriesListeFermee'

const base = { liste: Array.from({ length: 25 }, (_, i) => `c${i}`), fiches: 78139, par_categorie: [], exemples: [],
  manuelles_ignorees: 0, deja_regroupees: 0 }

describe('bilanSimulation (liste fermée des catégories)', () => {
  it('fiches à changer', () => {
    expect(bilanSimulation({ ...base, fiches_changees: 40000, categories_changees: 1100, manuelles_ignorees: 3 }))
      .toBe('40\u202f000 fiche(s) sur 78\u202f139 changeraient de catégorie (1\u202f100 catégories ramenées à 25), 3 corrigée(s) à la main laissée(s) telles quelles.')
  })
  it('déjà regroupé', () => {
    expect(bilanSimulation({ ...base, fiches_changees: 0, categories_changees: 0, deja_regroupees: 12 }))
      .toContain('déjà dans la liste (12 regroupées, annulable)')
  })
})
