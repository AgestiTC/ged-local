/**
 * Tests — préparation d'une photo avant envoi.
 *
 * Seule la partie **pure** est testée : jsdom n'a ni canvas ni `createImageBitmap`, et un
 * test qui les simulerait ne vérifierait que mes propres bouchons. Le calcul de proportions
 * est justement l'endroit où se logent les erreurs — un ratio inversé donne un portrait
 * déformé que personne ne remarque avant l'impression.
 */
import { describe, expect, it } from 'vitest'
import { COTE_MAX, dimensionsCibles } from '../../utils/image'

describe('dimensionsCibles', () => {
  it('réduit le côté long à la limite en gardant les proportions', () => {
    // Photo de téléphone en paysage : 4032 × 3024 (4/3).
    const r = dimensionsCibles(4032, 3024, 1024)
    expect(r.largeur).toBe(1024)
    expect(r.hauteur).toBe(768)
    expect(r.largeur / r.hauteur).toBeCloseTo(4032 / 3024, 2)
  })

  it('traite le portrait comme le paysage — c’est le côté LONG qui compte', () => {
    const r = dimensionsCibles(3024, 4032, 1024)
    expect(r.hauteur).toBe(1024)
    expect(r.largeur).toBe(768)
  })

  it('laisse intacte une image déjà plus petite', () => {
    // L'agrandir ajouterait du poids sans ajouter de détail.
    expect(dimensionsCibles(400, 300, 1024)).toEqual({ largeur: 400, hauteur: 300 })
  })

  it('laisse intacte une image pile à la limite', () => {
    expect(dimensionsCibles(1024, 512, 1024)).toEqual({ largeur: 1024, hauteur: 512 })
  })

  it('ne divise pas par zéro sur une image dégénérée', () => {
    expect(dimensionsCibles(0, 0, 1024)).toEqual({ largeur: 0, hauteur: 0 })
  })

  it('utilise 1024 par défaut', () => {
    expect(COTE_MAX).toBe(1024)
    expect(dimensionsCibles(2048, 2048).largeur).toBe(1024)
  })
})
