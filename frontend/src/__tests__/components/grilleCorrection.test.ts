import { describe, expect, it } from 'vitest'
import { correctionDepuis, depuisApercu } from '../../components/reports/GrilleCorrectionPanel'
import type { TemplateApercu } from '../../api'

// Grille fictive (aucune donnée réelle) : 2 critères, barème 0/10, notes sur 10.
const APERCU: TemplateApercu = {
  type: 'grille',
  criteres: [
    { nom: 'Délais', points: 40, documents: null, ligne: 4 },
    { nom: 'Valeur technique', points: 60, documents: null, ligne: 5 },
  ],
  nb_candidats: 2,
  bareme: [{ note: 0, libelle: 'Absent' }, { note: 10, libelle: 'Complet' }],
  note_max: 10,
  message: '',
}

describe('correctionDepuis', () => {
  it('rien de modifié : aucune correction envoyée', () => {
    const e = depuisApercu(APERCU)
    expect(correctionDepuis(e, depuisApercu(APERCU))).toBeNull()
  })

  it('n’envoie que les critères modifiés, avec leur ligne', () => {
    const initial = depuisApercu(APERCU)
    const courant = depuisApercu(APERCU)
    courant.criteres[1] = { ...courant.criteres[1], nom: ' Technique ', points: '55' }
    courant.criteres[0] = { ...courant.criteres[0], actif: false }
    expect(correctionDepuis(initial, courant)).toEqual({
      criteres: [
        { ligne: 4, nom: 'Délais', points: 40, actif: false },
        { ligne: 5, nom: 'Technique', points: 55, actif: true },
      ],
    })
  })

  it('barème et échelle : niveaux incomplets ignorés, barème vidé envoyé comme []', () => {
    const initial = depuisApercu(APERCU)
    const courant = { ...depuisApercu(APERCU), noteMax: '20',
      bareme: [{ note: '0', libelle: 'Absent' }, { note: '20', libelle: 'Excellent' }, { note: '', libelle: 'sans note' }] }
    expect(correctionDepuis(initial, courant)).toEqual({
      note_max: 20,
      bareme: [{ note: 0, libelle: 'Absent' }, { note: 20, libelle: 'Excellent' }],
    })
    expect(correctionDepuis(initial, { ...depuisApercu(APERCU), bareme: [] })).toEqual({ bareme: [] })
  })
})
