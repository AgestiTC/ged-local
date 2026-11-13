import { describe, expect, it } from 'vitest'
import { ilYa, nombre, pourcent, statutScan, tailleLisible, variation } from '../../utils/formatInventaire'

// Mêmes cas que les tests de rangement (`tests/test_carte_lecture.py`) : la mise en forme est la même.
describe('tailleLisible', () => {
  it.each([
    [0, '0 o'], [999, '999 o'], [1536, '1,5 Ko'], [5 * 1024 ** 2, '5 Mo'],
    [Math.trunc(3.2 * 1024 ** 4), '3,2 To'], [Math.trunc(12.4 * 1024 ** 4), '12,4 To'],
  ])('%s octets → %s', (octets, attendu) => {
    expect(tailleLisible(octets)).toBe(attendu)
  })
  it('taille inconnue', () => { expect(tailleLisible(null)).toBe('—') })
})

describe('nombre, variation, pourcent', () => {
  it('milliers séparés par une espace fine', () => {
    expect(nombre(182340)).toBe('182\u202f340')
    expect(nombre(7)).toBe('7')
  })
  it.each([
    [120 * 1024 ** 3, '+120 Go'], [-3 * 1024 ** 2, '\u22123 Mo'], [0, '='], [null, '—'],
  ])('variation %s → %s', (octets, attendu) => {
    expect(variation(octets)).toBe(attendu)
  })
  it('pourcentage insécable', () => { expect(pourcent(42)).toBe('42\u00a0%') })
})

describe('ilYa', () => {
  const maintenant = new Date('2026-10-14T12:00:00Z')
  it.each([
    [20, "à l'instant"], [5 * 60, 'il y a 5 min'], [3 * 3600, 'il y a 3 h'], [49 * 3600, 'il y a 2 j'],
  ])('%s s → %s', (secondes, attendu) => {
    expect(ilYa(new Date(maintenant.getTime() - secondes * 1000).toISOString(), maintenant)).toBe(attendu)
  })
  it('sans date', () => { expect(ilYa(null, maintenant)).toBe('jamais') })
  it('statut lisible', () => {
    expect(statutScan('termine')).toBe('terminé')
    expect(statutScan(null)).toBe('jamais scanné')
  })
})
