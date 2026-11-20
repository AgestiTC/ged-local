/**
 * Retours sur une réponse de l'IA (plan RAG, B3) : un clic s'enregistre, re-cliquer retire, un 👎 ouvre
 * les sources, un échec se dit et rien n'est perdu. Rendu réel (createRoot + act), API simulée. Fictif.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.unmock('react')

const juger = vi.fn()
vi.mock('../../api', () => ({ journalQuestionsApi: { juger: (...a: unknown[]) => juger(...a) } }))

import RetourReponse from '../../components/ia/RetourReponse'

const SOURCES = [{ id: 'doc-a', nom: 'a-fictif.pdf' }, { id: null, nom: 'sans-id.pdf' }]
const R = (extra: object = {}) => ({ avis: null, correction: null, sources: {}, ...extra })

let conteneur: HTMLDivElement
let racine: Root

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  conteneur = document.createElement('div')
  document.body.appendChild(conteneur)
  racine = createRoot(conteneur)
  juger.mockReset()
})
afterEach(() => {
  act(() => racine.unmount())
  conteneur.remove()
})

const afficher = async (props: Partial<Parameters<typeof RetourReponse>[0]> = {}) => {
  const onChange = vi.fn()
  await act(async () => {
    racine.render(<RetourReponse journalId="q1" sources={SOURCES} onChange={onChange} {...props} />)
  })
  return onChange
}
const parLabel = (l: string) => conteneur.querySelector<HTMLButtonElement>(`button[aria-label="${l}"]`)!
const cliquer = async (b: HTMLElement) => { await act(async () => { b.click() }) }

describe('RetourReponse', () => {
  it('👍 en un clic : envoyé seul, affiché enfoncé', async () => {
    juger.mockResolvedValue(R({ avis: 'utile' }))
    const onChange = await afficher()
    await cliquer(parLabel('Réponse utile'))
    expect(juger).toHaveBeenCalledWith('q1', { avis: 'utile' })
    expect(parLabel('Réponse utile').getAttribute('aria-pressed')).toBe('true')
    expect(onChange).toHaveBeenCalledWith(R({ avis: 'utile' }))
  })

  it('re-cliquer le même pouce retire l\'avis', async () => {
    juger.mockResolvedValue(null)
    await afficher({ valeur: R({ avis: 'utile' }) })
    await cliquer(parLabel('Réponse utile'))
    expect(juger).toHaveBeenCalledWith('q1', { avis: null })
    expect(parLabel('Réponse utile').getAttribute('aria-pressed')).toBe('false')
  })

  it('👎 ouvre les sources (seulement celles qui ont un identifiant), jugées une par une', async () => {
    juger.mockResolvedValueOnce(R({ avis: 'inutile' }))
    await afficher()
    await cliquer(parLabel('Réponse pas utile'))
    expect(conteneur.textContent).toContain('a-fictif.pdf')
    expect(conteneur.textContent).not.toContain('sans-id.pdf')
    juger.mockResolvedValueOnce(R({ avis: 'inutile', sources: { 'doc-a': 'hors_sujet' } }))
    await cliquer(parLabel('a-fictif.pdf : hors sujet'))
    expect(juger).toHaveBeenLastCalledWith('q1', { sources: { 'doc-a': 'hors_sujet' } })
    expect(parLabel('a-fictif.pdf : hors sujet').getAttribute('aria-pressed')).toBe('true')
  })

  it('un échec se dit et rend l\'état d\'avant', async () => {
    juger.mockRejectedValue(new Error('réseau'))
    await afficher()
    await cliquer(parLabel('Réponse utile'))
    expect(conteneur.textContent).toContain('Retour non enregistré')
    expect(parLabel('Réponse utile').getAttribute('aria-pressed')).toBe('false')
  })

  it('« Corriger » enregistre la bonne réponse', async () => {
    juger.mockResolvedValue(R({ correction: 'Réponse fictive corrigée' }))
    await afficher()
    await cliquer([...conteneur.querySelectorAll('button')].find(b => b.textContent?.includes('Corriger'))!)
    const zone = conteneur.querySelector('textarea')!
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
      setter.call(zone, 'Réponse fictive corrigée')
      zone.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await cliquer([...conteneur.querySelectorAll('button')].find(b => b.textContent === 'Enregistrer')!)
    expect(juger).toHaveBeenCalledWith('q1', { correction: 'Réponse fictive corrigée' })
    expect(conteneur.querySelector('textarea')).toBeNull()
    expect(conteneur.textContent).toContain('Votre correction : Réponse fictive corrigée')
  })
})
