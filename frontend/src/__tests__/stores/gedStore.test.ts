/**
 * Tests — gedStore (Zustand)
 * ============================
 * Teste la recherche, la pagination (load more), les filtres, les tags/catégories.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

// Réponse API de base incluant les champs de pagination
const BASE_SEARCH_RESPONSE = {
  resultats: [],
  total: 0,
  offset: 0,
  limit: 20,
  has_more: false,
}

vi.mock('../../api', () => ({
  searchApi: {
    search: vi.fn().mockResolvedValue(BASE_SEARCH_RESPONSE),
    getTags: vi.fn().mockResolvedValue({ tags: [] }),
    getCategories: vi.fn().mockResolvedValue({ categories: [] }),
  },
}))

import { useGEDStore } from '../../stores/gedStore'

// Résultats de test au format SearchResponse['resultats']
const RESULTATS = [
  {
    id: 'doc-1', nom: 'rapport.pdf', extension: 'pdf',
    taille_octets: 1_200_000, statut: 'enriched', score: 0.95,
    date_import: '2026-01-01',
    metadonnees_ia: { categorie: 'rapport', tags: ['annuel', '2025'], resume: 'Résumé', langue: 'fr' },
  },
  {
    id: 'doc-2', nom: 'contrat.docx', extension: 'docx',
    taille_octets: 350_000, statut: 'enriched', score: 0.82,
    date_import: '2026-01-02',
    metadonnees_ia: { categorie: 'contrat', tags: ['juridique'], resume: 'Contrat', langue: 'fr' },
  },
]

const RESET_STATE = {
  query: '',
  searchType: 'hybrid' as const,
  filters: {},
  results: [],
  total: 0,
  hasMore: false,
  currentOffset: 0,
  loading: false,
  loadingMore: false,
  error: null,
  tags: [],
  categories: [],
}

// ─── Setters ─────────────────────────────────────────────────────────────────

describe('gedStore — setters', () => {
  beforeEach(() => {
    useGEDStore.setState(RESET_STATE)
    vi.clearAllMocks()
  })

  it('setQuery met à jour la requête', () => {
    useGEDStore.getState().setQuery('contrat annuel')
    expect(useGEDStore.getState().query).toBe('contrat annuel')
  })

  it('setSearchType accepte text/semantic/hybrid', () => {
    useGEDStore.getState().setSearchType('semantic')
    expect(useGEDStore.getState().searchType).toBe('semantic')

    useGEDStore.getState().setSearchType('text')
    expect(useGEDStore.getState().searchType).toBe('text')

    useGEDStore.getState().setSearchType('hybrid')
    expect(useGEDStore.getState().searchType).toBe('hybrid')
  })

  it('setFilters met à jour les filtres', () => {
    useGEDStore.getState().setFilters({ categorie: 'rapport' })
    expect(useGEDStore.getState().filters.categorie).toBe('rapport')
  })

  it('clearResults remet query, results, total, hasMore et currentOffset à zéro', () => {
    useGEDStore.setState({
      query: 'test', results: RESULTATS, total: 2,
      hasMore: true, currentOffset: 20,
    })
    useGEDStore.getState().clearResults()

    const s = useGEDStore.getState()
    expect(s.query).toBe('')
    expect(s.results).toHaveLength(0)
    expect(s.total).toBe(0)
    expect(s.hasMore).toBe(false)
    expect(s.currentOffset).toBe(0)
  })
})

// ─── search() ────────────────────────────────────────────────────────────────

describe('gedStore — search()', () => {
  beforeEach(() => {
    useGEDStore.setState({ ...RESET_STATE, query: 'contrat' })
    vi.clearAllMocks()
  })

  it('exécute la recherche et stocke les résultats', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.search).mockResolvedValueOnce({
      ...BASE_SEARCH_RESPONSE,
      resultats: RESULTATS,
      total: 2,
    })

    await useGEDStore.getState().search()

    const s = useGEDStore.getState()
    expect(s.results).toHaveLength(2)
    expect(s.total).toBe(2)
    expect(s.loading).toBe(false)
    expect(s.error).toBeNull()
  })

  it('remet currentOffset à 0 et remplace les résultats (pas append)', async () => {
    // Simuler un état post-loadMore avec des résultats existants
    useGEDStore.setState({ results: RESULTATS, currentOffset: 20, hasMore: true })

    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.search).mockResolvedValueOnce({
      ...BASE_SEARCH_RESPONSE,
      resultats: [RESULTATS[0]],
      total: 1,
    })

    await useGEDStore.getState().search()

    const s = useGEDStore.getState()
    // Doit remplacer, pas accumuler
    expect(s.results).toHaveLength(1)
    expect(s.currentOffset).toBe(20) // PAGE_SIZE = 20
  })

  it('ne fait rien si la requête est vide', async () => {
    useGEDStore.setState({ query: '   ' })
    const { searchApi } = await import('../../api')

    await useGEDStore.getState().search()

    expect(vi.mocked(searchApi.search)).not.toHaveBeenCalled()
  })

  it('stocke l\'erreur en cas d\'échec', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.search).mockRejectedValueOnce(new Error('Timeout serveur'))

    await useGEDStore.getState().search()

    expect(useGEDStore.getState().error).toBe('Timeout serveur')
    expect(useGEDStore.getState().loading).toBe(false)
  })

  it('passe loading à true pendant la recherche', async () => {
    const { searchApi } = await import('../../api')
    let resolve!: (v: unknown) => void
    vi.mocked(searchApi.search).mockReturnValueOnce(
      new Promise(r => { resolve = r })
    )

    const promise = useGEDStore.getState().search()
    expect(useGEDStore.getState().loading).toBe(true)

    resolve(BASE_SEARCH_RESPONSE)
    await promise
    expect(useGEDStore.getState().loading).toBe(false)
  })

  it('passe les filtres à l\'API', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.search).mockResolvedValueOnce(BASE_SEARCH_RESPONSE)

    useGEDStore.setState({ query: 'test', filters: { categorie: 'facture', extension: 'pdf' } })
    await useGEDStore.getState().search()

    expect(vi.mocked(searchApi.search)).toHaveBeenCalledWith(
      expect.objectContaining({ categorie: 'facture', extension: 'pdf' })
    )
  })

  it('passe offset=0 à l\'API lors d\'une nouvelle recherche', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.search).mockResolvedValueOnce(BASE_SEARCH_RESPONSE)

    await useGEDStore.getState().search()

    expect(vi.mocked(searchApi.search)).toHaveBeenCalledWith(
      expect.objectContaining({ offset: 0 })
    )
  })

  it('stocke has_more depuis la réponse API', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.search).mockResolvedValueOnce({
      ...BASE_SEARCH_RESPONSE,
      total: 45,
      has_more: true,
      resultats: RESULTATS,
    })

    await useGEDStore.getState().search()

    expect(useGEDStore.getState().hasMore).toBe(true)
  })
})

// ─── loadMore() ──────────────────────────────────────────────────────────────

describe('gedStore — loadMore()', () => {
  beforeEach(() => {
    useGEDStore.setState({
      ...RESET_STATE,
      query: 'contrat',
      results: RESULTATS,
      total: 42,
      hasMore: true,
      currentOffset: 20,
    })
    vi.clearAllMocks()
  })

  it('accumule les résultats (append, pas replace)', async () => {
    const { searchApi } = await import('../../api')
    const NOUVEAUX = [{
      id: 'doc-3', nom: 'facture.xlsx', extension: 'xlsx',
      taille_octets: 50_000, statut: 'enriched', score: 0.70,
      date_import: '2026-01-03',
      metadonnees_ia: { categorie: 'facture', tags: [], resume: null, langue: 'fr' },
    }]
    vi.mocked(searchApi.search).mockResolvedValueOnce({
      ...BASE_SEARCH_RESPONSE,
      resultats: NOUVEAUX,
      total: 42,
      offset: 20,
      has_more: true,
    })

    await useGEDStore.getState().loadMore()

    const s = useGEDStore.getState()
    // Doit avoir les 2 existants + 1 nouveau
    expect(s.results).toHaveLength(3)
    expect(s.results[2].id).toBe('doc-3')
    expect(s.currentOffset).toBe(40) // 20 + PAGE_SIZE(20)
  })

  it('passe le bon offset à l\'API', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.search).mockResolvedValueOnce({
      ...BASE_SEARCH_RESPONSE, resultats: [], total: 42,
    })

    await useGEDStore.getState().loadMore()

    expect(vi.mocked(searchApi.search)).toHaveBeenCalledWith(
      expect.objectContaining({ offset: 20 })
    )
  })

  it('ne fait rien si hasMore est false', async () => {
    useGEDStore.setState({ hasMore: false })
    const { searchApi } = await import('../../api')

    await useGEDStore.getState().loadMore()

    expect(vi.mocked(searchApi.search)).not.toHaveBeenCalled()
  })

  it('ne fait rien si la requête est vide', async () => {
    useGEDStore.setState({ query: '' })
    const { searchApi } = await import('../../api')

    await useGEDStore.getState().loadMore()

    expect(vi.mocked(searchApi.search)).not.toHaveBeenCalled()
  })

  it('ne fait rien si loadingMore est déjà true (debounce)', async () => {
    useGEDStore.setState({ loadingMore: true })
    const { searchApi } = await import('../../api')

    await useGEDStore.getState().loadMore()

    expect(vi.mocked(searchApi.search)).not.toHaveBeenCalled()
  })

  it('remet loadingMore à false même en cas d\'erreur', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.search).mockRejectedValueOnce(new Error('Réseau'))

    await useGEDStore.getState().loadMore()

    expect(useGEDStore.getState().loadingMore).toBe(false)
  })
})

// ─── loadTags / loadCategories ────────────────────────────────────────────────

describe('gedStore — loadTags / loadCategories', () => {
  beforeEach(() => {
    useGEDStore.setState(RESET_STATE)
    vi.clearAllMocks()
  })

  it('loadTags charge les tags depuis l\'API', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.getTags).mockResolvedValueOnce({
      tags: [
        { tag: 'contrat', nb_documents: 5 },
        { tag: 'facture', nb_documents: 3 },
      ],
    })

    await useGEDStore.getState().loadTags()

    const tags = useGEDStore.getState().tags
    expect(tags).toHaveLength(2)
    expect(tags[0].tag).toBe('contrat')
  })

  it('loadTags ne plante pas si l\'API échoue', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.getTags).mockRejectedValueOnce(new Error('Erreur réseau'))

    await expect(useGEDStore.getState().loadTags()).resolves.toBeUndefined()
    expect(useGEDStore.getState().tags).toHaveLength(0)
  })

  it('loadCategories charge les catégories', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.getCategories).mockResolvedValueOnce({
      categories: [
        { categorie: 'rapport', nb_documents: 10 },
        { categorie: 'facture', nb_documents: 7 },
      ],
    })

    await useGEDStore.getState().loadCategories()

    const categories = useGEDStore.getState().categories
    expect(categories).toHaveLength(2)
    expect(categories[0].categorie).toBe('rapport')
  })

  it('loadCategories ne plante pas si l\'API échoue', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.getCategories).mockRejectedValueOnce(new Error('Réseau'))

    await expect(useGEDStore.getState().loadCategories()).resolves.toBeUndefined()
    expect(useGEDStore.getState().categories).toHaveLength(0)
  })
})
