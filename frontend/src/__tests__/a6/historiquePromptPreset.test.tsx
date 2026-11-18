/**
 * Historique d'un prompt pré-enregistré (A6) : liste des versions, « Restaurer » APRÈS confirmation.
 * Rendu réel (createRoot + act), API et confirmation simulées. Données fictives.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// setup.ts remplace les hooks de React (appel hors composant) : ici on veut le VRAI rendu.
vi.unmock('react')

const versions = vi.fn()
const restaurer = vi.fn()
const confirmer = vi.fn()

vi.mock('../../api', () => ({ promptsApi: { versions: (...a: unknown[]) => versions(...a), restaurer: (...a: unknown[]) => restaurer(...a) } }))
const toast = { success: vi.fn(), error: vi.fn() }
vi.mock('../../components/common/Toast', () => ({ useToast: () => toast }))
vi.mock('../../components/common/Confirmation', () => ({ confirmerTexte: (...a: unknown[]) => confirmer(...a) }))

import HistoriquePromptPreset from '../../components/settings/HistoriquePromptPreset'

const V = (version: number, prompt_text: string, commentaire: string | null = null) => ({
  version, nom: 'Preset fictif', prompt_text, description: null, categorie: 'rapport', modele_prefere: null,
  auteur: null, commentaire, created_at: '2026-11-18T10:00:00Z',
})

let conteneur: HTMLDivElement
let racine: Root

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  conteneur = document.createElement('div')
  document.body.appendChild(conteneur)
  racine = createRoot(conteneur)
  versions.mockReset(); restaurer.mockReset(); confirmer.mockReset()
  versions.mockResolvedValue({ id: 'p1', versions: [V(2, 'Texte fictif 2'), V(1, 'Texte fictif 1')] })
})

afterEach(() => {
  act(() => racine.unmount())
  conteneur.remove()
})

const afficher = async (onRestaure = vi.fn()) => {
  await act(async () => { racine.render(<HistoriquePromptPreset presetId="p1" onRestaure={onRestaure} />) })
  return onRestaure
}
const bouton = (texte: string) => [...conteneur.querySelectorAll('button')].find(b => b.textContent === texte)

describe('HistoriquePromptPreset', () => {
  it('liste les versions, la plus récente marquée « actuelle », sans « Restaurer » sur elle', async () => {
    await afficher()
    expect(versions).toHaveBeenCalledWith('p1')
    const lignes = conteneur.querySelectorAll('li')
    expect(lignes).toHaveLength(2)
    expect(lignes[0].textContent).toContain('v2')
    expect(lignes[0].textContent).toContain('actuelle')
    expect([...conteneur.querySelectorAll('button')].filter(b => b.textContent === 'Restaurer')).toHaveLength(1)
  })

  it('« Voir » affiche le texte de la version', async () => {
    await afficher()
    await act(async () => { [...conteneur.querySelectorAll('button')].filter(b => b.textContent === 'Voir')[1].click() })
    expect(conteneur.textContent).toContain('Texte fictif 1')
  })

  it('restaure après confirmation, puis recharge', async () => {
    confirmer.mockResolvedValue(true)
    restaurer.mockResolvedValue({ id: 'p1', nom: 'Preset fictif', prompt_text: 'Texte fictif 1', version: 3 })
    const onRestaure = await afficher()
    await act(async () => { bouton('Restaurer')!.click() })
    expect(confirmer).toHaveBeenCalledOnce()
    expect(restaurer).toHaveBeenCalledWith('p1', 1)
    expect(onRestaure).toHaveBeenCalledWith(expect.objectContaining({ prompt_text: 'Texte fictif 1' }))
    expect(versions).toHaveBeenCalledTimes(2)
  })

  it('ne restaure rien si la confirmation est refusée', async () => {
    confirmer.mockResolvedValue(false)
    await afficher()
    await act(async () => { bouton('Restaurer')!.click() })
    expect(restaurer).not.toHaveBeenCalled()
  })
})
