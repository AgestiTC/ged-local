import { describe, expect, it } from 'vitest'
import { candidatsDepuisSousDossiers, estDocumentMarche, groupesParDossier, repartirDossierConsultation } from '../../utils/groupesParDossier'

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

describe('candidatsDepuisSousDossiers', () => {
  it('un candidat par sous-dossier, préfixe commun retiré, sous-dossier vide écarté', () => {
    const { nouveaux, completes, vides } = candidatsDepuisSousDossiers([
      { nom: 'OFFRE_CES', document_ids: ['c1', 'c2'] },
      { nom: 'OFFRE_OTV', document_ids: ['o1'] },
      { nom: 'OFFRE_VIDE', document_ids: [] },
    ], [])
    expect(nouveaux).toEqual([
      { nom: 'CES', document_ids: ['c1', 'c2'] },
      { nom: 'OTV', document_ids: ['o1'] },
    ])
    expect(completes.size).toBe(0)
    expect(vides).toEqual(['OFFRE_VIDE'])
  })

  it('un candidat du même nom est complété, pas dupliqué', () => {
    const { nouveaux, completes } = candidatsDepuisSousDossiers([
      { nom: 'Durand', document_ids: ['d1', 'd2'] },
      { nom: 'Martin', document_ids: ['m1'] },
    ], [{ id: 'g1', nom: 'durand ', document_ids: ['d1'] }])
    expect(nouveaux.map(g => g.nom)).toEqual(['Martin'])
    expect(completes.get('g1')).toEqual(['d2'])
  })

  it('candidat existant déjà complet : rien à faire', () => {
    const { nouveaux, completes } = candidatsDepuisSousDossiers(
      [{ nom: 'Durand', document_ids: ['d1'] }],
      [{ id: 'g1', nom: 'Durand', document_ids: ['d1'] }])
    expect(nouveaux).toEqual([])
    expect(completes.size).toBe(0)
  })
})

describe('repartirDossierConsultation', () => {
  it('seul le CCTP de la racine va au marché ; DCE écarté ; autres sous-dossiers en candidats', () => {
    const r = repartirDossierConsultation(
      [
        { nom: 'OFFRE_CES', document_ids: ['c1'] },
        { nom: 'DCE', document_ids: ['d1', 'd2'] },
        { nom: 'OFFRE_OTV', document_ids: ['o1'] },
      ],
      [
        { id: 'cctp', nom: 'CCTP Lot 1.pdf' },
        { id: 'grille', nom: 'Grille analyse.xlsx' },
        { id: 'scan', nom: 'CCTP scan.pdf', exploitable: false },
      ])
    expect(r.candidats.map(s => s.nom)).toEqual(['OFFRE_CES', 'OFFRE_OTV'])
    expect(r.marche).toEqual(['cctp'])
    expect(r.ignores).toBe(2)
    expect(r.dossiersEcartes).toEqual(['DCE'])
  })

  it('reconnaît CCTP et règlement de consultation, pas un mot qui contient « rc »', () => {
    expect(estDocumentMarche('2026-CCTP_v2.docx')).toBe(true)
    expect(estDocumentMarche('Règlement de la consultation.pdf')).toBe(true)
    expect(estDocumentMarche('RC.pdf')).toBe(true)
    expect(estDocumentMarche('Marche_travaux.pdf')).toBe(false)
    expect(estDocumentMarche('Arcade.pdf')).toBe(false)
  })
})
