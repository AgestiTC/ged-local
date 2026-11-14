import { describe, expect, it } from 'vitest'
import { lienInterne } from '../../utils/lienInterne'

describe('lienInterne — lien porté par une notification', () => {
  it('suit une page de l\'application', () => {
    expect(lienInterne('/rangement?onglet=plan')).toBe('/rangement?onglet=plan')
    expect(lienInterne('/doublons')).toBe('/doublons')
  })

  it('refuse une adresse extérieure, y compris « //hôte »', () => {
    expect(lienInterne('https://exemple.invalid/')).toBeNull()
    expect(lienInterne('//exemple.invalid/x')).toBeNull()
    expect(lienInterne('javascript:alert(1)')).toBeNull()
    expect(lienInterne(null)).toBeNull()
    expect(lienInterne('')).toBeNull()
  })
})
