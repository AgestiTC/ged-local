import { describe, expect, it } from 'vitest'
import { ageDepot, lireTags, versPrefixe } from '../../utils/docApplications'

describe('versPrefixe — chemin collé par l\'admin → préfixe de règle', () => {
  it('chemin Windows UNC', () => {
    expect(versPrefixe('\\\\192.168.42.200\\Partage-Nas-Mato\\[GED]\\Docs-applications'))
      .toBe('smb://192.168.42.200/Partage-Nas-Mato/[GED]/Docs-applications/')
  })
  it('smb:// conservé, « / » final ajouté une seule fois', () => {
    expect(versPrefixe('smb://nas/p/Docs')).toBe('smb://nas/p/Docs/')
    expect(versPrefixe('smb://nas/p/Docs///')).toBe('smb://nas/p/Docs/')
  })
  it('vide → vide', () => {
    expect(versPrefixe('   ')).toBe('')
    expect(versPrefixe('\\\\')).toBe('')
  })
})

describe('ageDepot', () => {
  const maintenant = new Date('2026-11-16T12:00:00Z')
  it('jamais / aujourd\'hui / hier / il y a N jours', () => {
    expect(ageDepot(null, maintenant)).toBe('jamais')
    expect(ageDepot('2026-11-16T08:00:00Z', maintenant)).toBe("aujourd'hui")
    expect(ageDepot('2026-11-15T08:00:00Z', maintenant)).toBe('hier')
    expect(ageDepot('2026-11-04T12:00:00Z', maintenant)).toBe('il y a 12 jours')
  })
})

describe('lireTags', () => {
  it('virgules et points-virgules, sans vides ni doublons', () => {
    expect(lireTags(' doc-appli, a ;b,, a ')).toEqual(['doc-appli', 'a', 'b'])
  })
})
