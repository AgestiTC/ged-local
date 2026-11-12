/**
 * Tests — composants du bouton « IA LOCAL / IA GECO » (rendu statique + jsdom, sans testing-library).
 * Trois états affichables : local (lu), geco, inconnu. Le rôle Utilisateur garde l'INFORMATION mais pas le bouton.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('../../api', () => ({ systemApi: {} }))

import { BandeauIaGecoVue } from '../../components/ia/BandeauIaGeco'
import { BadgeIaChat, PhraseVideChat, MentionSidebar } from '../../components/ia/BadgesIa'
import { BoutonIaDestinationVue } from '../../components/ia/BoutonIaDestination'
import { PropositionRepliVue } from '../../components/ia/PropositionRepli'
import { MessageErreurIaVue } from '../../components/ia/MessageErreurIa'
import { choisirSelonDestination } from '../../components/ia/SelonDestination'
import { ConfirmationSortieInternet, clicAccepte, CLIC_IGNORE_MS } from '../../components/common/ConfirmationSortieInternet'
import { OptionsModeles } from '../../components/common/OptionsModeles'
import { useIaDestinationStore } from '../../stores/iaDestinationStore'
import type { ModeleListe } from '../../utils/modeles'
import type { EtatIa } from '../../utils/iaDestination'

const html = (el: ReactElement) => renderToStaticMarkup(el)
const dom = (el: ReactElement) => {
  const d = document.createElement('div')
  d.innerHTML = renderToStaticMarkup(el)
  return d
}
const non = () => {}
const ETATS: EtatIa[] = ['local', 'geco', 'inconnu']

describe('bandeau', () => {
  it("n'est PAS rendu en mode local, ni en état inconnu", () => {
    expect(html(<BandeauIaGecoVue destination="local" gecoModele="geco/x" admin onRevenir={non} />)).toBe('')
    expect(html(<BandeauIaGecoVue destination="inconnu" gecoModele="geco/x" admin onRevenir={non} />)).toBe('')
  })
  it('est rendu en mode GECO, pour TOUS les rôles : role=status, modèle, internet, indexation locale', () => {
    for (const admin of [true, false]) {
      const d = dom(<BandeauIaGecoVue destination="geco" gecoModele="geco/gros" admin={admin} onRevenir={non} />)
      const b = d.querySelector('[role="status"]')
      expect(b).not.toBeNull()
      expect(b!.textContent).toContain('IA GECO activée')
      expect(b!.textContent).toContain('geco/gros')
      expect(b!.textContent).toContain("L'indexation reste locale")
    }
  })
  it("bouton « Revenir à l'IA locale » : admin seulement", () => {
    const admin = dom(<BandeauIaGecoVue destination="geco" gecoModele="geco/x" admin onRevenir={non} />)
    expect(admin.querySelector('button')?.textContent).toContain("Revenir à l'IA locale")
    const autre = dom(<BandeauIaGecoVue destination="geco" gecoModele="geco/x" admin={false} onRevenir={non} />)
    expect(autre.querySelector('button')).toBeNull()
  })
  it("couleur d'avertissement (ambre), pas le rouge d'erreur", () => {
    const h = html(<BandeauIaGecoVue destination="geco" gecoModele="geco/x" admin onRevenir={non} />)
    expect(h).toContain('amber')
    expect(h).not.toContain('red-')
  })
})

describe('badges : trois états', () => {
  it('chat, en-tête : « 100% local » SEULEMENT en mode local lu', () => {
    expect(html(<BadgeIaChat destination="local" />)).toContain('100% local')
    for (const e of ['geco', 'inconnu'] as const) {
      const h = html(<BadgeIaChat destination={e} />)
      expect(h).not.toMatch(/100\s?%\s?local/)
      expect(h).not.toContain('ne quittent jamais')
    }
  })
  it('GECO : « IA GECO — internet » ; inconnu : « IA : vérification en cours… »', () => {
    expect(html(<BadgeIaChat destination="geco" />)).toContain('IA GECO — internet')
    expect(html(<BadgeIaChat destination="inconnu" />)).toContain('IA : vérification en cours…')
  })
  it("chat, écran vide : la promesse de confidentialité n'existe qu'en local lu", () => {
    expect(html(<PhraseVideChat destination="local" />)).toContain('ne quittent jamais Matothèque')
    for (const e of ['geco', 'inconnu'] as const) {
      const h = html(<PhraseVideChat destination={e} />)
      expect(h).not.toMatch(/100\s?%\s?local/)
      expect(h).not.toContain('ne quittent jamais')
    }
  })
  it('barre latérale', () => {
    expect(html(<MentionSidebar version="1.0" destination="local" />)).toContain('v1.0 — 100% local')
    expect(html(<MentionSidebar version="1.0" destination="geco" />)).toContain('IA GECO — internet')
    expect(html(<MentionSidebar version="1.0" destination="inconnu" />)).toContain('vérification en cours')
    for (const e of ['geco', 'inconnu'] as const) {
      expect(html(<MentionSidebar version="1.0" destination={e} />)).not.toMatch(/100\s?%\s?local/)
    }
  })
})

describe('bouton IA LOCAL / IA GECO (en-tête)', () => {
  const vue = (destination: EtatIa, admin: boolean, extra: { occupe?: boolean; nonVerifie?: boolean } = {}) => (
    <BoutonIaDestinationVue destination={destination} admin={admin} occupe={!!extra.occupe}
      nonVerifie={extra.nonVerifie} onLocal={non} onGeco={non} />)
  const rendre = (...a: Parameters<typeof vue>) => dom(vue(...a))

  it('rôle Utilisateur : le bouton N\'EST PAS RENDU du tout (aucun état, aucune infobulle)', () => {
    for (const e of ETATS) expect(html(vue(e, false))).toBe('')
  })
  it('admin : deux positions lisibles, état courant porté par aria-pressed', () => {
    const d = rendre('local', true)
    const [local, geco] = [...d.querySelectorAll('button')]
    expect(local.textContent).toContain('IA LOCAL')
    expect(geco.textContent).toContain('IA GECO')
    expect(local.getAttribute('aria-pressed')).toBe('true')
    expect(geco.getAttribute('aria-pressed')).toBe('false')
    expect([...rendre('geco', true).querySelectorAll('button')].map(b => b.getAttribute('aria-pressed'))).toEqual(['false', 'true'])
  })
  it('état inconnu : AUCUNE position pressée, pastille « non vérifié »', () => {
    const d = rendre('inconnu', true)
    expect([...d.querySelectorAll('button')].map(b => b.getAttribute('aria-pressed'))).toEqual(['false', 'false'])
    expect(d.querySelector('[aria-label="état non vérifié"]')).not.toBeNull()
  })
  it('lecture en échec après un état connu : état gardé + pastille discrète « non vérifié »', () => {
    const d = rendre('geco', true, { nonVerifie: true })
    expect(d.querySelectorAll('button')[1].getAttribute('aria-pressed')).toBe('true')
    expect(d.querySelector('[aria-label="état non vérifié"]')?.getAttribute('title')).toMatch(/non vérifié/)
    expect(rendre('geco', true).querySelector('[aria-label="état non vérifié"]')).toBeNull()
  })
  it("« IA LOCAL » reste actif même quand l'écran affiche déjà local, et appelle onLocal", () => {
    const onLocal = vi.fn()
    const el = BoutonIaDestinationVue({ destination: 'local', admin: true, occupe: false, onLocal, onGeco: non }) as ReactElement<{ children: ReactElement[] }>
    const boutons = (el.props.children[0] as ReactElement<{ children: ReactElement<{ onClick: () => void; disabled: boolean }>[] }>).props.children
    expect(boutons[0].props.disabled).toBe(false)
    boutons[0].props.onClick()
    expect(onLocal).toHaveBeenCalledTimes(1)
  })
  it('occupé (PUT en vol) : boutons inactifs et aria-busy', () => {
    const d = rendre('local', true, { occupe: true })
    for (const b of d.querySelectorAll('button')) expect(b.disabled).toBe(true)
    expect(d.querySelector('[role="group"]')?.getAttribute('aria-busy')).toBe('true')
  })
  it('contraste : texte sombre sur ambre, blanc sur vert foncé (jamais blanc sur ambre clair)', () => {
    const h = html(vue('geco', true))
    expect(h).toContain('bg-amber-200 text-amber-950')
    expect(html(vue('local', true))).toContain('bg-emerald-800 text-white')
  })
})

describe('proposition de repli (chat)', () => {
  it("n'est rendue que si `visible`", () => {
    expect(html(<PropositionRepliVue visible={false} onAccepter={non} />)).toBe('')
    const d = dom(<PropositionRepliVue visible onAccepter={non} />)
    expect(d.textContent).toContain("L'IA locale ne répond pas — passer sur IA GECO ?")
    expect(d.querySelector('button')).not.toBeNull()
  })
})

describe("message d'erreur persistant de la bascule", () => {
  it('rien sans message ; sinon role=alert, texte du serveur tel quel, bouton pour fermer', () => {
    expect(html(<MessageErreurIaVue message={null} onFermer={non} />)).toBe('')
    const d = dom(<MessageErreurIaVue message="Activer « IA GECO » exige l'authentification active et un compte administrateur" onFermer={non} />)
    expect(d.querySelector('[role="alert"]')?.textContent).toContain("exige l'authentification active et un compte administrateur")
    expect(d.querySelector('button')?.getAttribute('aria-label')).toMatch(/Fermer/)
  })
})

describe('SelonDestination', () => {
  const c = { local: 'LOCAL', geco: 'GECO', inconnu: 'INCONNU' }
  it('un contenu par état ; jamais le texte « local » hors état local lu', () => {
    expect(choisirSelonDestination('local', c)).toBe('LOCAL')
    expect(choisirSelonDestination('geco', c)).toBe('GECO')
    expect(choisirSelonDestination('inconnu', c)).toBe('INCONNU')
  })
})

describe('fenêtre de confirmation de sortie internet', () => {
  beforeEach(() => useIaDestinationStore.setState({ destination: 'local' }))

  it('rend titre (aria-labelledby), message, Annuler puis Continuer ; pied personnalisable', () => {
    const d = dom(<ConfirmationSortieInternet titre="T" message={<p>corps</p>} pied={<p>pied perso</p>}
      onAnnuler={vi.fn()} onConfirmer={vi.fn()} />)
    const dialogue = d.querySelector('[role="alertdialog"]')!
    const titre = d.querySelector('h2')!
    expect(dialogue.getAttribute('aria-labelledby')).toBe(titre.id)
    expect(d.textContent).toContain('corps')
    expect(d.textContent).toContain('pied perso')
    expect(d.textContent).not.toContain('Aucun document')
    expect([...d.querySelectorAll('button')].map(b => b.textContent)).toEqual(['Annuler', 'Continuer'])
  })
  it('pied par défaut, local lu : celui des sorties existantes', () => {
    const d = dom(<ConfirmationSortieInternet titre="T" message="m" onAnnuler={non} onConfirmer={non} />)
    expect(d.textContent).toContain('100% local')
    expect(d.textContent).toContain('Aucun document')
  })
  it("pied par défaut, mode GECO : exact, sans « 100% local »", () => {
    useIaDestinationStore.setState({ destination: 'geco' })
    const d = dom(<ConfirmationSortieInternet titre="T" message="m" onAnnuler={non} onConfirmer={non} />)
    expect(d.textContent).toContain("Cette action n'envoie aucun document. L'IA GECO est par ailleurs activée.")
    expect(d.textContent).not.toMatch(/100\s?%\s?local/)
  })
  it('pied par défaut, état inconnu : jamais « 100% local »', () => {
    useIaDestinationStore.setState({ destination: 'inconnu' })
    const d = dom(<ConfirmationSortieInternet titre="T" message="m" onAnnuler={non} onConfirmer={non} />)
    expect(d.textContent).not.toMatch(/100\s?%\s?local/)
  })
  it('occupé : « Continuer » inactif et occupé', () => {
    const d = dom(<ConfirmationSortieInternet titre="T" message="m" occupe onAnnuler={non} onConfirmer={non} />)
    const [annuler, continuer] = [...d.querySelectorAll('button')]
    expect(continuer.disabled).toBe(true)
    expect(continuer.getAttribute('aria-busy')).toBe('true')
    expect(annuler.disabled).toBe(true)
  })
  it("clics ignorés pendant ~300 ms après l'ouverture", () => {
    expect(CLIC_IGNORE_MS).toBe(300)
    expect(clicAccepte(1000, 1100)).toBe(false)
    expect(clicAccepte(1000, 1299)).toBe(false)
    expect(clicAccepte(1000, 1300)).toBe(true)
  })
})

describe("sélecteurs : modèles GECO d'embeddings masqués, mention ciblée", () => {
  const geco = (name: string, extra: Partial<ModeleListe> = {}): ModeleListe =>
    ({ name, origine: 'GECO', selectionnable: true, ...extra })
  it("un modèle GECO d'embeddings n'apparaît jamais", () => {
    const d = dom(<select><OptionsModeles modeles={[]}
      externes={[geco('geco/chat'), geco('geco/text-embedding-nomic', { embedding: true })]} /></select>)
    expect([...d.querySelectorAll('option')].map(o => o.value)).toEqual(['geco/chat'])
  })
  it('si seuls des embeddings existent, aucun groupe GECO vide', () => {
    const d = dom(<select><OptionsModeles modeles={[]} externes={[geco('geco/e', { embedding: true })]} /></select>)
    expect(d.querySelectorAll('optgroup')).toHaveLength(0)
  })
  it("« réservé au mode IA GECO » : seulement les options d'origine GECO non sélectionnables", () => {
    const d = dom(<select><OptionsModeles
      modeles={[{ name: 'local-bloque', origine: 'MATO', selectionnable: false }]}
      externes={[geco('geco/a', { selectionnable: false })]} /></select>)
    const parNom = Object.fromEntries([...d.querySelectorAll('option')].map(o => [o.value, o.textContent]))
    expect(parNom['geco/a']).toContain('réservé au mode IA GECO')
    expect(parNom['local-bloque']).not.toContain('réservé au mode IA GECO')
  })
})
