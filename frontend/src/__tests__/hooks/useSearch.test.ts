/**
 * Tests — useSearch hook
 * =======================
 * Vérifie que le hook expose correctement toutes les données et actions du gedStore,
 * y compris les champs de pagination (hasMore, loadMore, loadingMore, currentOffset).
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

const BASE_RESPONSE = {
  resultats: [], total: 0, offset: 0, limit: 20, has_more: false,
}

vi.mock('../../api', () => ({
  searchApi: {
    search: vi.fn().mockResolvedValue(BASE_RESPONSE),
    getTags: vi.fn().mockResolvedValue({ tags: [] }),
    getCategories: vi.fn().mockResolvedValue({ categories: [] }),
  },
}))

import { useGEDStore } from '../../stores/gedStore'
import { useSearch } from '../../hooks/useSearch'

const RESET = {
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

const RESULTATS = [
  {
    id: 'doc-1', nom: 'rapport.pdf', extension: 'pdf',
    taille_octets: 1_000_000, statut: 'enriched', score: 0.95,
    date_import: '2026-01-01',
    metadonnees_ia: { categorie: 'rapport', tags: ['annuel'], resume: 'Résumé', langue: 'fr' },
  },
]

describe('useSearch — données exposées', () => {
  beforeEach(() => {
    useGEDStore.setState(RESET)
    vi.clearAllMocks()
  })

  it('expose query, searchType, filters', () => {
    const hook = useSearch()
    expect(hook.query).toBe('')
    expect(hook.searchType).toBe('hybrid')
    expect(hook.filters).toEqual({})
  })

  it('expose results, total, loading, error', () => {
    const hook = useSearch()
    expect(hook.results).toEqual([])
    expect(hook.total).toBe(0)
    expect(hook.loading).toBe(false)
    expect(hook.error).toBeNull()
  })

  it('expose hasMore, currentOffset, loadingMore', () => {
    const hook = useSearch()
    expect(hook.hasMore).toBe(false)
    expect(hook.currentOffset).toBe(0)
    expect(hook.loadingMore).toBe(false)
  })

  it('expose tags et categories', () => {
    const hook = useSearch()
    expect(hook.tags).toEqual([])
    expect(hook.categories).toEqual([])
  })

  it('reflète les changements du store (hasMore)', () => {
    useGEDStore.setState({ hasMore: true, currentOffset: 20 })
    const hook = useSearch()
    expect(hook.hasMore).toBe(true)
    expect(hook.currentOffset).toBe(20)
  })

  it('reflète les résultats du store', () => {
    useGEDStore.setState({ results: RESULTATS, total: 1 })
    const hook = useSearch()
    expect(hook.results).toHaveLength(1)
    expect(hook.total).toBe(1)
  })
})

describe('useSearch — actions exposées', () => {
  beforeEach(() => {
    useGEDStore.setState(RESET)
    vi.clearAllMocks()
  })

  it('expose setQuery, setSearchType, setFilters', () => {
    const hook = useSearch()
    expect(typeof hook.setQuery).toBe('function')
    expect(typeof hook.setSearchType).toBe('function')
    expect(typeof hook.setFilters).toBe('function')
  })

  it('expose search, loadMore, clearResults', () => {
    const hook = useSearch()
    expect(typeof hook.search).toBe('function')
    expect(typeof hook.loadMore).toBe('function')
    expect(typeof hook.clearResults).toBe('function')
  })

  it('expose loadTags, loadCategories', () => {
    const hook = useSearch()
    expect(typeof hook.loadTags).toBe('function')
    expect(typeof hook.loadCategories).toBe('function')
  })

  it('setQuery met à jour la requête dans le store', () => {
    useSearch().setQuery('contrat 2026')
    expect(useGEDStore.getState().query).toBe('contrat 2026')
  })

  it('setSearchType met à jour le mode de recherche', () => {
    useSearch().setSearchType('semantic')
    expect(useGEDStore.getState().searchType).toBe('semantic')
  })

  it('setFilters met à jour les filtres', () => {
    useSearch().setFilters({ categorie: 'facture', extension: 'pdf' })
    expect(useGEDStore.getState().filters.categorie).toBe('facture')
    expect(useGEDStore.getState().filters.extension).toBe('pdf')
  })

  it('clearResults remet query, results, hasMore et currentOffset à zéro', () => {
    useGEDStore.setState({ query: 'test', results: RESULTATS, total: 1, hasMore: true, currentOffset: 20 })
    useSearch().clearResults()
    const s = useGEDStore.getState()
    expect(s.query).toBe('')
    expect(s.results).toHaveLength(0)
    expect(s.hasMore).toBe(false)
    expect(s.currentOffset).toBe(0)
  })

  it('search() appelle l\'API avec la requête et les filtres', async () => {
    const { searchApi } = await import('../../api')
    vi.mocked(searchApi.search).mockResolvedValueOnce(BASE_RESPONSE)

    useGEDStore.setState({ query: 'rapport annuel', filters: { categorie: 'rapport' } })
    await useSearch().search()

    expect(vi.mocked(searchApi.search)).toHaveBeenCalledWith(
      expect.objectContaining({ q: 'rapport annuel', categorie: 'rapport' })
    )
  })

  it('loadMore() ne fait rien si hasMore=false', async () => {
    const { searchApi } = await import('../../api')
    useGEDStore.setState({ hasMore: false, query: 'test' })

    await useSearch().loadMore()

    expect(vi.mocked(searchApi.search)).not.toHaveBeenCalled()
  })

  it('loadMore() ne fait rien si la requête est vide', async () => {
    const { searchApi } = await import('../../api')
    useGEDStore.setState({ hasMore: true, query: '' })

    await useSearch().loadMore()

    expect(vi.mocked(searchApi.search)).not.toHaveBeenCalled()
  })
})
