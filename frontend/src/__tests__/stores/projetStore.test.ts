import { describe, expect, it } from 'vitest'
import { avecDerniereComparaison } from '../../stores/projetStore'

const res = (ref: string, created_at: string, libelle = 'Tableau comparatif') =>
  ({ id: ref, type: 'job', ref, libelle, created_at })

describe('avecDerniereComparaison', () => {
  it('reprend la DERNIÈRE comparaison rattachée quand le projet ne la mémorisait pas', () => {
    const etat = avecDerniereComparaison({
      etat: { comparatif: { groupes: [1, 2] } },
      resultats: [res('ancien', '2026-10-01T10:00:00Z'), res('recent', '2026-10-11T23:15:00Z'), res('r', '2026-10-12T00:00:00Z', 'Rapport')],
    })
    expect(etat.comparatif).toEqual({ groupes: [1, 2], compareJobId: 'recent' })
  })

  it('ne touche à rien si la comparaison est déjà mémorisée, ou sans comparatif', () => {
    const memorise = { comparatif: { compareJobId: 'x' } }
    expect(avecDerniereComparaison({ etat: memorise, resultats: [res('y', '2026-10-12T00:00:00Z')] })).toEqual(memorise)
    expect(avecDerniereComparaison({ etat: {}, resultats: [res('y', '2026-10-12T00:00:00Z')] })).toEqual({})
  })
})
