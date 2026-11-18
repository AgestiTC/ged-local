import { afterEach, describe, expect, it, vi } from 'vitest'
import { chatApi } from '../../api'

// A6 : la page IA internet désigne sa consigne système par sa CLÉ ; aucun texte ne transite.
describe('chatApi.stream — consigne système par clé', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  const lancer = async (cle?: string) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('ok', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await chatApi.stream([{ role: 'user', content: 'Question fictive' }], '', false, () => {}, undefined, undefined, cle)
    return JSON.parse(fetchMock.mock.calls[0][1].body as string)
  }

  it('envoie consigne_systeme et seulement les messages de la conversation', async () => {
    const corps = await lancer('internet.formulation')
    expect(corps.consigne_systeme).toBe('internet.formulation')
    expect(corps.messages).toEqual([{ role: 'user', content: 'Question fictive' }])
    expect(corps.use_ged).toBe(false)
  })

  it("n'envoie rien de plus sans clé (autres pages du chat inchangées)", async () => {
    const corps = await lancer()
    expect('consigne_systeme' in corps).toBe(false)
  })
})
