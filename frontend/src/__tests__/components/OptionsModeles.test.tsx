import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { OptionsModeles } from '../../components/common/OptionsModeles'
import type { ModeleListe } from '../../utils/modeles'

// Rendu des enfants d'un <select>, analysé dans le DOM (jsdom).
function rendre(props: Parameters<typeof OptionsModeles>[0]): HTMLSelectElement {
  const div = document.createElement('div')
  div.innerHTML = renderToStaticMarkup(<select><OptionsModeles {...props} /></select>)
  return div.querySelector('select') as HTMLSelectElement
}

const mato = (name: string): ModeleListe => ({ name, origine: 'MATO', selectionnable: true })
const geco = (name: string, selectionnable: boolean): ModeleListe => ({ name, origine: 'GECO', selectionnable })

describe('OptionsModeles', () => {
  it('un seul groupe : l\'optgroup MATO est quand même rendu', () => {
    const s = rendre({ modeles: [mato('llama3.1')] })
    const groupes = s.querySelectorAll('optgroup')
    expect(groupes).toHaveLength(1)
    expect(groupes[0].label).toBe('MATO')
  })

  it('GECO avant MATO, options triées, value = nom, title = nom complet', () => {
    const s = rendre({ modeles: [mato('b'), mato('a')], externes: [geco('g', true)] })
    expect([...s.querySelectorAll('optgroup')].map(g => g.label)).toEqual(['GECO', 'MATO'])
    const opts = [...s.querySelectorAll('option')]
    expect(opts.map(o => o.value)).toEqual(['g', 'a', 'b'])
    expect(opts[1].title).toBe('a')
  })

  it('option désactivée quand selectionnable === false, avec la mention', () => {
    const o = rendre({ modeles: [], externes: [geco('g', false)] }).querySelector('option')!
    expect(o.disabled).toBe(true)
    expect(o.textContent).toContain('internet — réservé au mode IA GECO')
  })

  it('option GECO activée quand selectionnable === true, mention « internet »', () => {
    const o = rendre({ modeles: [], externes: [geco('g', true)] }).querySelector('option')!
    expect(o.disabled).toBe(false)
    expect(o.textContent).toContain('internet')
    expect(o.textContent).not.toContain('réservé au mode IA GECO')
  })

  it('on se fie à selectionnable, pas à l\'origine : MATO non sélectionnable = désactivé', () => {
    const o = rendre({ modeles: [{ name: 'x', origine: 'MATO', selectionnable: false }] }).querySelector('option')!
    expect(o.disabled).toBe(true)
  })

  it('selectionnable absent (ancien backend) : option activée, sans mention', () => {
    const o = rendre({ modeles: [{ name: 'x' }] }).querySelector('option')!
    expect(o.disabled).toBe(false)
    expect(o.textContent).toBe('x')
  })

  it('libellé personnalisé', () => {
    const o = rendre({ modeles: [mato('x')], libelle: m => `« ${m.name} »` }).querySelector('option')!
    expect(o.textContent).toBe('« x »')
  })

  it('libellé personnalisé : réservé aux modèles installés, un externe garde son nom + mention', () => {
    const s = rendre({ modeles: [mato('x')], externes: [geco('g', true)], libelle: m => m.name.toUpperCase() })
    expect([...s.querySelectorAll('option')].map(o => o.textContent)).toEqual(['g · internet', 'X'])
  })

  it('filtre : les modèles écartés disparaissent, et un groupe vidé aussi', () => {
    const s = rendre({
      modeles: [mato('embed-x'), mato('llama')],
      externes: [geco('embed-g', true)],
      filtre: m => !m.name.startsWith('embed'),
    })
    expect([...s.querySelectorAll('option')].map(o => o.value)).toEqual(['llama'])
    expect([...s.querySelectorAll('optgroup')].map(g => g.label)).toEqual(['MATO'])
  })

  it('rien à afficher : aucun optgroup', () => {
    expect(rendre({ modeles: [] }).querySelectorAll('optgroup')).toHaveLength(0)
  })
})
