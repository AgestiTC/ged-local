import { describe, expect, it } from 'vitest'
import { grouperModeles } from '../../utils/modeles'
import type { ModeleListe } from '../../utils/modeles'

const mato = (name: string, extra: Partial<ModeleListe> = {}): ModeleListe =>
  ({ name, origine: 'MATO', selectionnable: true, ...extra })
const geco = (name: string, selectionnable = false): ModeleListe =>
  ({ name, origine: 'GECO', selectionnable })

describe('grouperModeles', () => {
  it('GECO d\'abord, puis MATO, puis les autres groupes par ordre alphabétique', () => {
    const r = grouperModeles(
      [mato('a'), { name: 'z', origine: 'ZETA' }, { name: 'b', origine: 'ALPHA' }],
      [geco('g')],
    )
    expect(r.map(g => g.groupe)).toEqual(['GECO', 'MATO', 'ALPHA', 'ZETA'])
  })

  it('tri insensible à la casse et aux accents, dans chaque groupe', () => {
    const r = grouperModeles([mato('zeta'), mato('Éclair'), mato('alpha'), mato('Beta')])
    expect(r[0].modeles.map(m => m.name)).toEqual(['alpha', 'Beta', 'Éclair', 'zeta'])
  })

  it('un modèle sans origine (ancien backend) tombe dans MATO', () => {
    const r = grouperModeles([{ name: 'vieux' }, mato('neuf')])
    expect(r).toHaveLength(1)
    expect(r[0].groupe).toBe('MATO')
    expect(r[0].modeles.map(m => m.name)).toEqual(['neuf', 'vieux'])
  })

  it('un groupe vide n\'est pas rendu', () => {
    expect(grouperModeles([], [])).toEqual([])
    expect(grouperModeles([], undefined)).toEqual([])
    expect(grouperModeles([mato('a')], []).map(g => g.groupe)).toEqual(['MATO'])
    expect(grouperModeles([], [geco('g')]).map(g => g.groupe)).toEqual(['GECO'])
  })

  it('ne mute pas ses entrées', () => {
    const m = [mato('b'), mato('a')]
    const e = [geco('y'), geco('x')]
    const copieM = JSON.parse(JSON.stringify(m))
    const copieE = JSON.parse(JSON.stringify(e))
    grouperModeles(m, e)
    expect(m).toEqual(copieM)
    expect(e).toEqual(copieE)
  })

  it('conserve les champs de chaque modèle (même référence)', () => {
    const x = mato('a', { size: 42 })
    expect(grouperModeles([x])[0].modeles[0]).toBe(x)
  })
})

describe('grouperModeles — clé de tri', () => {
  it('trie sur le libellé affiché quand il diffère du nom', () => {
    const court = (m: { name: string }) => m.name.replace(/^hf\.co\/[^/]+\//, '')
    const g = grouperModeles([{ name: 'hf.co/org/Zebre' }, { name: 'llama3.1' }], undefined, court)
    expect(g[0].modeles.map(m => m.name)).toEqual(['llama3.1', 'hf.co/org/Zebre'])
  })
})
