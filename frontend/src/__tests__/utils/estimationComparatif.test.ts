import { describe, expect, it } from 'vitest'
import { dureeLisible, estimerRestantMs } from '../../utils/estimationComparatif'

describe('estimerRestantMs', () => {
  it('moyenne mesurée × candidats restants', () => {
    // 2 candidats traités en 10 min → 5 min chacun ; 4 restants → 20 min.
    expect(estimerRestantMs(0, 10 * 60_000, 2, 6)).toBe(20 * 60_000)
  })
  it('rien à estimer avant le 1er candidat fini, ni une fois tout fini', () => {
    expect(estimerRestantMs(null, null, 0, 6)).toBeNull()
    expect(estimerRestantMs(0, null, 0, 6)).toBeNull()
    expect(estimerRestantMs(0, 1000, 6, 6)).toBeNull()
  })
})

describe('dureeLisible', () => {
  it('secondes, minutes, heures', () => {
    expect(dureeLisible(45_000)).toBe('45 s')
    expect(dureeLisible(3 * 60_000)).toBe('3 min')
    expect(dureeLisible(65 * 60_000)).toBe('1 h 05')
  })
})
