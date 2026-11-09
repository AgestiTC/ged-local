/**
 * Tests — chatStore (Zustand) : mode GED, migration du persist, lecture des en-têtes de sources.
 * Données fictives.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

const { stream } = vi.hoisted(() => ({ stream: vi.fn() }))

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
    stream.mockReset()
    useChatStore.setState({ messages: [], input: '', model: '', gedMode: 'auto', streaming: false, _abort: null })
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

  it.each(['auto', 'jamais'] as const)("envoie ged_mode=%s, sans gedSources dans messages", async (mode) => {
    const { corps, meta } = await appeler(mode)
    expect(corps.ged_mode).toBe(mode)
    expect(corps).not.toHaveProperty('use_ged')
    expect(corps.messages).toEqual([{ role: 'user', content: 'bonjour' }])
    expect(meta).toHaveBeenCalledWith({ gedUtilise: false, sources: [] })
  })
})
