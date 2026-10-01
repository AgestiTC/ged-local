import { describe, expect, it } from 'vitest'
import { groupesParDossier } from '../../utils/groupesParDossier'

const base = 'smb://192.168.42.200/Partage-Nas-Mato/[MaTo]/MLB/TestIA'

describe('groupesParDossier', () => {
  it('un groupe par dossier de candidat, préfixe commun retiré (cas réel du 01/10/2026)', () => {
    const { groupes, ecartes } = groupesParDossier([
      { id: 'c1', chemin: `${base}/OFFRE_CES/OFFRE/1-Lot1-AE.pdf` },
      { id: 'c2', chemin: `${base}/OFFRE_CES/OFFRE/6_2-Planning.pdf` },
      { id: 'o1', chemin: `${base}/OFFRE_OTV/L1-6.1 Mémoire.pdf` },
      { id: 'z', chemin: `${base}/OFFRE_CES.zip` },
      { id: 'g', chemin: `${base}/MA26001_RAO_Lot1.xlsx` },
    ])
    expect(groupes).toEqual([
      { nom: 'CES', document_ids: ['c1', 'c2'] },
      { nom: 'OTV', document_ids: ['o1'] },
    ])
    expect(ecartes).toBe(2)
  })

  it('pas de coupe au milieu d\'un mot', () => {
    const { groupes } = groupesParDossier([
      { id: 'a', chemin: '/d/OFFICE/a.pdf' },
      { id: 'b', chemin: '/d/OFFRE/b.pdf' },
    ])
    expect(groupes.map(g => g.nom)).toEqual(['OFFICE', 'OFFRE'])
  })

  it('chemins Windows et sélection vide', () => {
    expect(groupesParDossier([]).groupes).toEqual([])
    const { groupes } = groupesParDossier([
      { id: 'a', chemin: 'T:\\AO\\Martin\\a.pdf' },
      { id: 'b', chemin: 'T:\\AO\\Durand\\sous\\b.pdf' },
    ])
    expect(groupes.map(g => g.nom)).toEqual(['Martin', 'Durand'])
  })
})
