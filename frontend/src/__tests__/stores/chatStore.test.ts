/**
 * Tests — chatStore (Zustand) : mode GED, migration du persist, lecture des en-têtes de sources.
 * Données fictives.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

const { stream, refus } = vi.hoisted(() => ({ stream: vi.fn(), refus: vi.fn() }))

// Garde de destination IA : simulée (ses propres tests sont dans utils/gardeEnvoiIa.test.ts).
vi.mock('../../utils/gardeEnvoiIa', () => ({ refusEnvoiIa: refus }))

vi.mock('../../api', async (importOriginal) => {
  const reel = await importOriginal<typeof import('../../api')>()
  return { ...reel, chatApi: { stream } }
})

import { migrerChat, useChatStore } from '../../stores/chatStore'
import { lireEntetesGed } from '../../api'

const entetes = (o: Record<string, string>) => new Headers(o)

describe('migrerChat (persist v0 → v1)', () => {
  it("useGed:true devient 'toujours' (choix explicite conservé)", () => {
    const r = migrerChat({ messages: [], model: 'x', useGed: true }, 0)
    expect(r.gedMode).toBe('toujours')
    expect(r).not.toHaveProperty('useGed')
    expect(r.model).toBe('x')
  })
  it("useGed:false devient 'auto' (l'ancien défaut n'était pas un choix)", () => {
    expect(migrerChat({ useGed: false }, 0).gedMode).toBe('auto')
  })
  it("état vide ou null → 'auto'", () => {
    expect(migrerChat(null, 0).gedMode).toBe('auto')
  })
  it('v1 inchangé', () => {
    expect(migrerChat({ gedMode: 'jamais' }, 1).gedMode).toBe('jamais')
  })
  it("v1 avec valeur invalide → 'auto'", () => {
    expect(migrerChat({ gedMode: 'peut-etre' }, 1).gedMode).toBe('auto')
    expect(migrerChat({}, 1).gedMode).toBe('auto')
  })
})

describe('lireEntetesGed', () => {
  it('décode le JSON percent-encodé, accents compris', () => {
    const src = [{ id: 'abc', nom: 'licence é.pdf' }]
    const m = lireEntetesGed(entetes({
      'X-Ged-Utilise': '1', 'X-Ged-Sources': encodeURIComponent(JSON.stringify(src)),
    }))
    expect(m).toEqual({ gedUtilise: true, sources: [{ id: 'abc', nom: 'licence é.pdf' }] })
  })
  it('X-Ged-Utilise: 0 → pas de sources', () => {
    expect(lireEntetesGed(entetes({ 'X-Ged-Utilise': '0', 'X-Ged-Sources': '%5B%5D' })))
      .toEqual({ gedUtilise: false, sources: [] })
  })
  it('X-Rag-Question → journalId (B3), même sans source GED', () => {
    expect(lireEntetesGed(entetes({ 'X-Ged-Utilise': '0', 'X-Rag-Question': 'q-fictive' })))
      .toEqual({ gedUtilise: false, sources: [], journalId: 'q-fictive' })
  })
  it('en-têtes absents ou corrompus → GED non utilisée, sans exception', () => {
    expect(lireEntetesGed(entetes({})).gedUtilise).toBe(false)
    expect(lireEntetesGed(entetes({ 'X-Ged-Utilise': '1', 'X-Ged-Sources': '%E0%A4%A' })).gedUtilise).toBe(false)
    expect(lireEntetesGed(entetes({ 'X-Ged-Utilise': '1', 'X-Ged-Sources': '%7B%7D' })).gedUtilise).toBe(false)
  })
  it('id absent → null', () => {
    const m = lireEntetesGed(entetes({
      'X-Ged-Utilise': '1', 'X-Ged-Sources': encodeURIComponent(JSON.stringify([{ nom: 'a.pdf' }])),
    }))
    expect(m.sources).toEqual([{ id: null, nom: 'a.pdf' }])
  })
})

describe('useChatStore', () => {
  beforeEach(() => {
    stream.mockReset(); refus.mockReset()
    refus.mockResolvedValue(null)   // par défaut : la destination est vérifiée, on envoie
    useChatStore.setState({ messages: [], input: '', model: '', gedMode: 'auto', streaming: false, _abort: null, alerte: null })
  })

  it("garde bloquante : l'API d'envoi N'est PAS appelée, la saisie est conservée, l'alerte est posée", async () => {
    refus.mockResolvedValue("L'IA GECO vient d'être activée : cette demande partirait par internet chez GECO. Renvoyez-la pour confirmer.")
    useChatStore.setState({ input: 'ma question' })
    await useChatStore.getState().envoyer()
    expect(stream).not.toHaveBeenCalled()
    const s = useChatStore.getState()
    expect(s.input).toBe('ma question')
    expect(s.messages).toHaveLength(0)
    expect(s.alerte).toContain("L'IA GECO vient d'être activée")
    expect(s.streaming).toBe(false)
  })

  it('garde passante : envoi normal, alerte effacée', async () => {
    stream.mockResolvedValue('ok')
    useChatStore.setState({ input: 'bonjour', alerte: 'ancienne' })
    await useChatStore.getState().envoyer()
    expect(stream).toHaveBeenCalledTimes(1)
    expect(useChatStore.getState().alerte).toBeNull()
  })

  it("erreurIaLocale : posée sur un flux « ⚠️ IA injoignable (…) » renvoyé par le serveur", async () => {
    stream.mockImplementation(async (_m, _mod, _g, onChunk) => {
      onChunk('⚠️ IA injoignable (connexion refusée)'); return '⚠️ IA injoignable (connexion refusée)'
    })
    useChatStore.setState({ input: 'bonjour' })
    await useChatStore.getState().envoyer()
    expect(useChatStore.getState().messages.at(-1)!.erreurIaLocale).toBe(true)
  })

  it('erreurIaLocale : posée sur un échec réseau du chat', async () => {
    stream.mockRejectedValue(new Error('boom'))
    useChatStore.setState({ input: 'bonjour' })
    await useChatStore.getState().envoyer()
    expect(useChatStore.getState().messages.at(-1)!.erreurIaLocale).toBe(true)
  })

  it('erreurIaLocale : PAS posée pour un refus (ChatRefus), ni une erreur GECO « ⚠️ <message> », ni une réponse normale', async () => {
    const { ChatRefus } = await import('../../api')
    stream.mockRejectedValue(new ChatRefus('Modèle GECO refusé'))
    useChatStore.setState({ input: 'a' })
    await useChatStore.getState().envoyer()
    expect(useChatStore.getState().messages.at(-1)!.erreurIaLocale).toBeFalsy()

    stream.mockImplementation(async (_m, _mod, _g, onChunk) => { onChunk('⚠️ GECO a répondu 502'); return '⚠️ GECO a répondu 502' })
    useChatStore.setState({ input: 'b', messages: [] })
    await useChatStore.getState().envoyer()
    expect(useChatStore.getState().messages.at(-1)!.erreurIaLocale).toBeFalsy()

    stream.mockImplementation(async (_m, _mod, _g, onChunk) => { onChunk('Bonjour'); return 'Bonjour' })
    useChatStore.setState({ input: 'c', messages: [] })
    await useChatStore.getState().envoyer()
    expect(useChatStore.getState().messages.at(-1)!.erreurIaLocale).toBeFalsy()
  })

  it("erreurIaLocale n'est jamais persistée (ne réapparaît pas au rechargement)", () => {
    const opts = (useChatStore as unknown as { persist: { getOptions: () => { partialize: (s: unknown) => { messages: { erreurIaLocale?: boolean }[] } } } }).persist.getOptions()
    const sortie = opts.partialize({
      messages: [{ role: 'assistant', content: '⚠️ IA injoignable.', erreurIaLocale: true }], model: '', gedMode: 'auto',
    })
    expect(sortie.messages[0]).not.toHaveProperty('erreurIaLocale')
    expect(sortie.messages[0]).toMatchObject({ role: 'assistant', content: '⚠️ IA injoignable.' })
  })

  it("défaut 'auto' et setGedMode", () => {
    expect(useChatStore.getState().gedMode).toBe('auto')
    useChatStore.getState().setGedMode('jamais')
    expect(useChatStore.getState().gedMode).toBe('jamais')
  })

  it('envoie le mode GED et rattache les sources au message assistant', async () => {
    stream.mockImplementation(async (_m, _mod, _ged, onChunk, _sig, onMeta) => {
      onMeta({ gedUtilise: true, sources: [{ id: '1', nom: 'doc-fictif.pdf' }] })
      onChunk('Bonjour')
      return 'Bonjour'
    })
    useChatStore.setState({ input: 'licence de Thomas ?', gedMode: 'toujours' })
    await useChatStore.getState().envoyer()
    expect(stream.mock.calls[0][2]).toBe('toujours')
    const dernier = useChatStore.getState().messages.at(-1)!
    expect(dernier.role).toBe('assistant')
    expect(dernier.content).toBe('Bonjour')
    expect(dernier.gedSources).toEqual([{ id: '1', nom: 'doc-fictif.pdf' }])
  })

  it('sources reçues puis erreur avant le 1er chunk → message sans gedSources', async () => {
    stream.mockImplementation(async (_m, _mod, _ged, _onChunk, _sig, onMeta) => {
      onMeta({ gedUtilise: true, sources: [{ id: '1', nom: 'doc-fictif.pdf' }] })
      throw new Error('boom')
    })
    useChatStore.setState({ input: 'licence de Thomas ?' })
    await useChatStore.getState().envoyer()
    const dernier = useChatStore.getState().messages.at(-1)!
    expect(dernier.content).toContain('IA injoignable')
    expect(dernier.gedSources).toBeUndefined()
  })

  it('refus du serveur (ChatRefus) → son message est affiché, pas « IA injoignable »', async () => {
    const { ChatRefus } = await import('../../api')
    stream.mockImplementation(async () => { throw new ChatRefus('Modèle « x » non installé') })
    useChatStore.setState({ input: 'bonjour' })
    await useChatStore.getState().envoyer()
    const dernier = useChatStore.getState().messages.at(-1)!
    expect(dernier.content).toContain('Modèle « x » non installé')
    expect(dernier.content).not.toContain('injoignable')
  })

  it('GED non utilisée → pas de gedSources', async () => {
    stream.mockImplementation(async (_m, _mod, _ged, onChunk, _sig, onMeta) => {
      onMeta({ gedUtilise: false, sources: [] })
      onChunk('Salut')
      return 'Salut'
    })
    useChatStore.setState({ input: 'écris un mail' })
    await useChatStore.getState().envoyer()
    expect(useChatStore.getState().messages.at(-1)!.gedSources).toBeUndefined()
  })
})

describe('chatApi.stream — corps réel (fetch mocké)', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  async function appeler(ged: 'auto' | 'jamais') {
    const reel = await vi.importActual<typeof import('../../api')>('../../api')
    const fetchMock = vi.fn().mockResolvedValue(new Response('ok', {
      status: 200, headers: { 'X-Ged-Utilise': '0', 'X-Ged-Sources': '%5B%5D' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const meta = vi.fn()
    await reel.chatApi.stream(
      [{ role: 'user', content: 'bonjour', gedSources: [{ id: '1', nom: 'secret.pdf' }] }],
      '', ged, () => {}, undefined, meta,
    )
    return { corps: JSON.parse(fetchMock.mock.calls[0][1].body as string), meta }
  }

  it('réponse 400 : l\'erreur porte le `detail` du serveur ; sans JSON, repli « chat HTTP »', async () => {
    const reel = await vi.importActual<typeof import('../../api')>('../../api')
    const appel = () => reel.chatApi.stream([{ role: 'user', content: 'x' }], 'm', 'auto', () => {})
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'Modèle « m » non installé' }), { status: 400 })))
    await expect(appel()).rejects.toThrow('Modèle « m » non installé')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('boom', { status: 502 })))
    // Sans `detail`, ce n'est PAS un refus : erreur ordinaire (l'écran dira « IA injoignable »).
    const { ChatRefus } = await import('../../api')
    const erreur = await appel().catch((e: unknown) => e)
    expect(erreur).toBeInstanceOf(Error)
    expect(erreur).not.toBeInstanceOf(ChatRefus)
  })

  it.each(['auto', 'jamais'] as const)("envoie ged_mode=%s, sans gedSources dans messages", async (mode) => {
    const { corps, meta } = await appeler(mode)
    expect(corps.ged_mode).toBe(mode)
    expect(corps).not.toHaveProperty('use_ged')
    expect(corps.messages).toEqual([{ role: 'user', content: 'bonjour' }])
    expect(meta).toHaveBeenCalledWith({ gedUtilise: false, sources: [] })
  })
})
