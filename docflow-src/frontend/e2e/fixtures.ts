/**
 * Playwright — Fixtures et helpers partagés
 * ==========================================
 * Fournit des helpers réutilisables et des mocks API
 * pour les tests E2E qui ne nécessitent pas de backend réel.
 */

import { test as base, expect, type Page, type Route } from '@playwright/test'

// ─── Types ───────────────────────────────────────────────────────────────────

interface MockDocument {
  id: string
  nom: string
  extension: string
  statut: string
  source: string
  hash_sha256: string
  date_import: string
  taille_octets: number
  chemin: string
}

// ─── Données de test ─────────────────────────────────────────────────────────

export const MOCK_DOCUMENTS: MockDocument[] = [
  {
    id: 'doc-e2e-001',
    nom: 'rapport_annuel_2025.pdf',
    extension: 'pdf',
    statut: 'enriched',
    source: 'upload',
    hash_sha256: 'abc123def456',
    date_import: '2026-01-15T10:30:00Z',
    taille_octets: 2_456_789,
    chemin: '/documents/rapport_annuel_2025.pdf',
  },
  {
    id: 'doc-e2e-002',
    nom: 'contrat_prestation_2026.docx',
    extension: 'docx',
    statut: 'enriched',
    source: 'watch',
    hash_sha256: 'def456ghi789',
    date_import: '2026-02-10T14:00:00Z',
    taille_octets: 145_678,
    chemin: '/documents/contrat_prestation_2026.docx',
  },
  {
    id: 'doc-e2e-003',
    nom: 'facture_Q1_2026.xlsx',
    extension: 'xlsx',
    statut: 'enriched',
    source: 'drag_drop',
    hash_sha256: 'ghi789jkl012',
    date_import: '2026-03-01T09:00:00Z',
    taille_octets: 89_000,
    chemin: '/documents/facture_Q1_2026.xlsx',
  },
]

export const MOCK_SEARCH_RESULTS = [
  {
    id: 'doc-e2e-001',
    nom: 'rapport_annuel_2025.pdf',
    extension: 'pdf',
    taille_octets: 2_456_789,
    statut: 'enriched',
    score: 0.9512,
    date_import: '2026-01-15T10:30:00Z',
    metadonnees_ia: {
      categorie: 'rapport',
      tags: ['annuel', '2025', 'bilan'],
      resume: 'Rapport annuel de l\'exercice 2025 avec bilan financier et perspectives.',
      langue: 'fr',
    },
  },
]

// ─── Helpers de mock API ──────────────────────────────────────────────────────

export async function mockDocumentsAPI(page: Page) {
  await page.route('**/api/documents*', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total: MOCK_DOCUMENTS.length,
        page: 1,
        page_size: 20,
        pages: 1,
        documents: MOCK_DOCUMENTS,
      }),
    })
  })
}

export async function mockSearchAPI(page: Page) {
  await page.route('**/api/search*', async (route: Route) => {
    const url = new URL(route.request().url())
    const q = url.searchParams.get('q') ?? ''

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        query: q,
        type: 'hybrid',
        total: q ? MOCK_SEARCH_RESULTS.length : 0,
        resultats: q ? MOCK_SEARCH_RESULTS : [],
      }),
    })
  })
}

export async function mockFoldersAPI(page: Page) {
  await page.route('**/api/folders*', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        dossiers: [
          {
            id: 'folder-e2e-001',
            chemin: 'C:/Documents/DocFlow',
            nom_affichage: 'Documents DocFlow',
            actif: true,
            recursive: true,
            dernier_scan: '2026-04-13T10:00:00Z',
          },
        ],
      }),
    })
  })
}

export async function mockTagsAndCategoriesAPI(page: Page) {
  await page.route('**/api/search/tags*', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total: 3,
        tags: [
          { tag: 'contrat', nb_documents: 5 },
          { tag: 'facture', nb_documents: 3 },
          { tag: 'rapport', nb_documents: 8 },
        ],
      }),
    })
  })

  await page.route('**/api/search/categories*', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total: 2,
        categories: [
          { categorie: 'rapport', nb_documents: 8 },
          { categorie: 'contrat', nb_documents: 5 },
        ],
      }),
    })
  })
}

export async function mockModelsAPI(page: Page) {
  // Proxy backend — ModelSelector appelle /api/generate/models (évite CORS Ollama)
  await page.route('**/api/generate/models', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        models: [
          { name: 'mixtral:latest' },
          { name: 'mistral:latest' },
        ],
      }),
    })
  })
}

export async function mockStatsAPI(page: Page) {
  await page.route('**/api/documents/stats*', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_documents: 3,
        par_statut: { enriched: 2, pending: 1 },
        taille_totale_octets: 2_691_467,
        categories: [
          { categorie: 'rapport', nb_documents: 2 },
          { categorie: 'facture', nb_documents: 1 },
        ],
      }),
    })
  })
}

export async function mockHealthAPI(page: Page) {
  await page.route('**/health', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        version: '0.5.0',
        services: {
          tika: { url: 'http://localhost:9998', disponible: true },
          ollama: { url: 'http://localhost:11434', disponible: true },
        },
      }),
    })
  })
}

export async function mockPromptsAPI(page: Page) {
  await page.route('**/api/prompts*', async (route: Route) => {
    const method = route.request().method()
    if (method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          prompts: [
            {
              id: 'prompt-e2e-001',
              nom: 'Synthèse de contrat',
              description: 'Extrait les clauses principales d\'un contrat',
              prompt_text: 'Analyse ce contrat et liste les clauses essentielles.',
              categorie: 'extraction',
              modele_prefere: 'mixtral:latest',
            },
          ],
          total: 1,
        }),
      })
    } else if (method === 'POST') {
      const body = await route.request().postDataJSON()
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ id: 'prompt-e2e-new', ...body }),
      })
    } else if (method === 'PUT') {
      const body = await route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 'prompt-e2e-001', ...body }),
      })
    } else if (method === 'DELETE') {
      await route.fulfill({ status: 204 })
    } else {
      await route.continue()
    }
  })
}

export async function mockTemplatesAPI(page: Page) {
  await page.route('**/api/templates*', async (route: Route) => {
    const method = route.request().method()
    if (method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          templates: [
            {
              id: 'tpl-e2e-001',
              nom: 'Rapport mensuel',
              description: 'Template de rapport mensuel standard',
              type: 'docx',
              champs: [
                { nom: 'titre', type: 'text', description: 'Titre du rapport' },
                { nom: 'date', type: 'text', description: 'Date du rapport' },
                { nom: 'resume', type: 'text', description: 'Résumé exécutif' },
              ],
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
          total: 1,
        }),
      })
    } else if (method === 'DELETE') {
      await route.fulfill({ status: 204 })
    } else {
      await route.continue()
    }
  })
}

// ─── Fixture personnalisée : app avec mocks complets ─────────────────────────

export const test = base.extend<{ mockedPage: Page }>({
  mockedPage: async ({ page }, use) => {
    await mockHealthAPI(page)
    await mockDocumentsAPI(page)
    await mockSearchAPI(page)
    await mockFoldersAPI(page)
    await mockTagsAndCategoriesAPI(page)
    await mockModelsAPI(page)
    await mockStatsAPI(page)
    await mockPromptsAPI(page)
    await mockTemplatesAPI(page)

    await use(page)
  },
})

export { expect }
