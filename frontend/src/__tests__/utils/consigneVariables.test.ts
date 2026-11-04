import { describe, expect, it } from 'vitest'
import { contientVariables, correspondAuMotif, resoudreConsigne, roleMarche } from '../../utils/consigneVariables'

const CONSIGNE = `Tu es ingénieur territorial, membre de la commission d'analyse des offres de l'appel d'offres [DOSSIER PARENT].
Tu évalues l'offre du candidat sur chaque sous-critère technique et valeur environnementale, de façon factuelle et objective.

Chaque sous-critère est noté selon le règlement de consultation [ un fichier nommé *RC_MOE_COLLEBASSE*] .
N'invente rien.`

describe('resoudreConsigne', () => {
  it('cas réel du 04/11/2026 : dossier remplacé, fichier retiré du texte et retenu', () => {
    const r = resoudreConsigne(CONSIGNE, 'MA26050')
    expect(r.texte).toContain("de l'appel d'offres MA26050.")
    expect(r.texte).toContain('noté selon le règlement de consultation.\n')
    expect(r.texte).not.toContain('[')
    expect(r.motifs).toEqual(['RC_MOE_COLLEBASSE'])
    expect(r.dossierManquant).toBe(false)
  })

  it('sans dossier connu : la variable reste et le manque est signalé', () => {
    const r = resoudreConsigne('Appel d\'offres [dossier parent].', null)
    expect(r.texte).toBe('Appel d\'offres [dossier parent].')
    expect(r.dossierManquant).toBe(true)
  })

  it('consigne sans variable : inchangée', () => {
    expect(contientVariables('Compare les prix [important].')).toBe(false)
    expect(resoudreConsigne('Compare les prix [important].', 'X').texte).toBe('Compare les prix [important].')
    expect(contientVariables(CONSIGNE)).toBe(true)
  })
})

describe('correspondAuMotif', () => {
  it('ignore casse, accents et séparateurs', () => {
    expect(correspondAuMotif('RC MOE Collebasse.pdf', 'RC_MOE_COLLEBASSE')).toBe(true)
    expect(correspondAuMotif('2026-rc-moe_collebasse v2.docx', 'RC_MOE_COLLEBASSE')).toBe(true)
    expect(correspondAuMotif('CCTP_COLLEBASSE.pdf', 'RC_MOE_COLLEBASSE')).toBe(false)
  })
})

describe('roleMarche', () => {
  it('CCTP, RC, ou rien', () => {
    expect(roleMarche('CCTP Lot 1.pdf')).toBe('CCTP')
    expect(roleMarche('RC_MOE_COLLEBASSE.pdf')).toBe('RC')
    expect(roleMarche('Règlement de la consultation.pdf')).toBe('RC')
    expect(roleMarche('Arcade.pdf')).toBe(null)
  })
})
