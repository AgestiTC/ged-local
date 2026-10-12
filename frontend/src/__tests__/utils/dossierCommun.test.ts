import { describe, expect, it } from 'vitest'
import { dossierCommun } from '../../utils/dossierCommun'

const base = 'smb://192.168.42.200/Partage/[MaTo]/MLB/AO'

describe('dossierCommun', () => {
  it('dossier commun du candidat, sous-dossiers compris', () => {
    expect(dossierCommun([`${base}/OFFRE_A/OFFRE/1-AE.pdf`, `${base}/OFFRE_A/6-Planning.pdf`])).toBe(`${base}/OFFRE_A`)
  })
  it('un seul document : son dossier', () => {
    expect(dossierCommun([`${base}/OFFRE_A/memoire.pdf`])).toBe(`${base}/OFFRE_A`)
  })
  it('refuse un dossier trop haut (racine du partage)', () => {
    expect(dossierCommun(['smb://hote/Partage/a.pdf', 'smb://hote/Partage/b/c.pdf'])).toBeNull()
    expect(dossierCommun([])).toBeNull()
  })
})

import { nomCandidat, nomUnique } from '../../utils/dossierCommun'

describe('nomCandidat / nomUnique', () => {
  it('nom tiré du dossier, sans préfixe générique', () => {
    expect(nomCandidat('smb://nas/P/AO/OFFRE_CES')).toBe('CES')
    expect(nomCandidat('smb://nas/P/AO/Offre - Durand SA')).toBe('Durand SA')
    expect(nomCandidat('smb://nas/P/AO/Martin_Freres')).toBe('Martin Freres')
    expect(nomCandidat('smb://nas/P/AO/OFFRE')).toBe('OFFRE')
    expect(nomCandidat(null)).toBe('')
  })
  it('suffixe si le nom est déjà pris', () => {
    expect(nomUnique('CES', ['OTV'])).toBe('CES')
    expect(nomUnique('CES', ['ces', 'CES (2)'])).toBe('CES (3)')
  })
})
