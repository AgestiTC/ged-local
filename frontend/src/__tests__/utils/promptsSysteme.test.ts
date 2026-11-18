import { describe, expect, it } from 'vitest'
import {
  diffLignes, ecartVariables, libelleUsage, libelleVersion, regrouperParUsage, resumeDiff, variablesDuTexte,
} from '../../utils/promptsSysteme'

describe('prompts système — libellés', () => {
  it('nomme la version active', () => {
    expect(libelleVersion(0, false)).toBe('origine')
    expect(libelleVersion(3, true)).toBe('origine')    // dernière version = retour à l'origine
    expect(libelleVersion(3, false)).toBe('v3')
  })

  it('traduit les usages connus, garde les autres', () => {
    expect(libelleUsage('enrichissement')).toMatch(/Enrichissement/)
    expect(libelleUsage('inconnu')).toBe('inconnu')
  })
})

describe('prompts système — regroupement par usage', () => {
  it('groupe, ordonne les usages et trie les clés', () => {
    const g = regrouperParUsage([
      { cle: 'b.analyse', usage: 'analyse' }, { cle: 'vision', usage: 'vision' },
      { cle: 'a.analyse', usage: 'analyse' }, { cle: 'enrichissement', usage: 'enrichissement' },
      { cle: 'x', usage: 'zz-nouveau' },
    ])
    expect(g.map(x => x.usage)).toEqual(['enrichissement', 'vision', 'analyse', 'zz-nouveau'])
    expect(g[2].prompts.map(p => p.cle)).toEqual(['a.analyse', 'b.analyse'])
    expect(regrouperParUsage([])).toEqual([])
  })
})

describe('prompts système — différence ligne à ligne', () => {
  it('textes identiques : aucune différence', () => {
    const d = diffLignes('a\nb', 'a\nb')
    expect(d.every(l => l.type === 'egal')).toBe(true)
    expect(resumeDiff(d)).toEqual({ ajouts: 0, retraits: 0 })
  })

  it('repère ligne modifiée, ajoutée et retirée', () => {
    const d = diffLignes('un\ndeux\ntrois\nquatre', 'un\nDEUX\ntrois\ncinq\nquatre')
    expect(d).toEqual([
      { type: 'egal', texte: 'un' },
      { type: 'retrait', texte: 'deux' },
      { type: 'ajout', texte: 'DEUX' },
      { type: 'egal', texte: 'trois' },
      { type: 'ajout', texte: 'cinq' },
      { type: 'egal', texte: 'quatre' },
    ])
    expect(resumeDiff(d)).toEqual({ ajouts: 2, retraits: 1 })
  })

  it('gère les extrémités et le texte vide', () => {
    expect(diffLignes('a\nb', 'b')).toEqual([{ type: 'retrait', texte: 'a' }, { type: 'egal', texte: 'b' }])
    expect(diffLignes('a', 'a\nz')).toEqual([{ type: 'egal', texte: 'a' }, { type: 'ajout', texte: 'z' }])
    expect(resumeDiff(diffLignes('', 'x\ny'))).toEqual({ ajouts: 2, retraits: 1 })   // '' compte pour une ligne vide
  })
})

describe('prompts système — variables du gabarit', () => {
  it('lit les variables, ignore les accolades doublées et les formats', () => {
    expect(variablesDuTexte('{a} et {{littéral}} puis {b:g} et {a}')).toEqual(['a', 'b'])
  })

  it('signale manquantes et inconnues, sauf pour un texte littéral', () => {
    expect(ecartVariables('{tableau} {autre}', ['tableau', 'attentes']))
      .toEqual({ manquantes: ['attentes'], inconnues: ['autre'] })
    expect(ecartVariables('JSON : {"a": 1}', [])).toEqual({ manquantes: [], inconnues: [] })
  })
})
