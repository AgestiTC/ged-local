/**
 * Tests E2E mockés — Page GED avec API simulée
 * =============================================
 * Teste la recherche, les filtres, et les résultats avec des données mockées.
 * Fonctionne SANS backend réel.
 */

import { test, expect, MOCK_SEARCH_RESULTS } from '../fixtures'

test.describe('GED — recherche avec résultats mockés', () => {
  test.beforeEach(async ({ mockedPage }) => {
    await mockedPage.goto('/ged')
    await mockedPage.waitForLoadState('networkidle')
  })

  test('les catégories mockées s\'affichent dans la sidebar', async ({ mockedPage }) => {
    await expect(mockedPage.getByText('rapport')).toBeVisible({ timeout: 3000 })
    await expect(mockedPage.getByText('contrat')).toBeVisible({ timeout: 3000 })
  })

  test('les tags mockés s\'affichent dans la sidebar', async ({ mockedPage }) => {
    await expect(mockedPage.getByText('facture')).toBeVisible({ timeout: 3000 })
  })

  test('une recherche affiche les résultats mockés', async ({ mockedPage }) => {
    const input = mockedPage.getByPlaceholder(/rechercher dans vos documents/i)
    await input.fill('rapport')
    await mockedPage.getByRole('button', { name: /rechercher/i }).click()

    // Le document mocké doit apparaître
    await expect(
      mockedPage.getByText(MOCK_SEARCH_RESULTS[0].nom)
    ).toBeVisible({ timeout: 5000 })
  })

  test('le score de pertinence est affiché', async ({ mockedPage }) => {
    const input = mockedPage.getByPlaceholder(/rechercher dans vos documents/i)
    await input.fill('rapport')
    await mockedPage.getByRole('button', { name: /rechercher/i }).click()

    // Le score (95%) doit être affiché
    await expect(
      mockedPage.getByText(/95%/).first()
    ).toBeVisible({ timeout: 5000 })
  })

  test('la catégorie du résultat est affichée', async ({ mockedPage }) => {
    const input = mockedPage.getByPlaceholder(/rechercher dans vos documents/i)
    await input.fill('rapport')
    await mockedPage.getByRole('button', { name: /rechercher/i }).click()

    await expect(
      mockedPage.getByText('rapport').first()
    ).toBeVisible({ timeout: 5000 })
  })

  test('cliquer sur un résultat ouvre le panneau latéral', async ({ mockedPage }) => {
    const input = mockedPage.getByPlaceholder(/rechercher dans vos documents/i)
    await input.fill('rapport')
    await mockedPage.getByRole('button', { name: /rechercher/i }).click()

    await mockedPage.waitForTimeout(1000)

    const firstResult = mockedPage.getByText(MOCK_SEARCH_RESULTS[0].nom).first()
    await firstResult.waitFor({ state: 'visible', timeout: 5000 })
    await firstResult.click()

    // Le panneau latéral doit s'ouvrir
    await expect(
      mockedPage.getByText(/utiliser dans un rapport/i).or(
        mockedPage.getByText(/informations/i).first()
      )
    ).toBeVisible({ timeout: 3000 })
  })

  test('effacer la recherche vide les résultats', async ({ mockedPage }) => {
    const input = mockedPage.getByPlaceholder(/rechercher dans vos documents/i)
    await input.fill('rapport')
    await mockedPage.getByRole('button', { name: /rechercher/i }).click()
    await mockedPage.waitForTimeout(1000)

    // Cliquer sur effacer
    const clearBtn = mockedPage.getByRole('button', { name: /effacer/i }).or(
      mockedPage.locator('button[title="Effacer"]')
    ).first()
    await clearBtn.waitFor({ state: 'visible', timeout: 3000 })
    await clearBtn.click()

    // La recherche est effacée
    await expect(input).toHaveValue('')

    // L'état vide doit réapparaître
    await expect(
      mockedPage.getByText(/recherche hybride/i).or(
        mockedPage.getByText(/importez des documents/i)
      ).first()
    ).toBeVisible({ timeout: 3000 })
  })
})

test.describe('GED — filtrer par catégorie', () => {
  test.beforeEach(async ({ mockedPage }) => {
    await mockedPage.goto('/ged')
    await mockedPage.waitForLoadState('networkidle')
  })

  test('cliquer sur un tag lance une recherche avec ce tag', async ({ mockedPage }) => {
    // Attendre que les tags soient chargés
    await mockedPage.getByText('contrat').waitFor({ state: 'visible', timeout: 3000 })

    // Cliquer sur le tag "contrat"
    await mockedPage.getByText('contrat').first().click()

    // La barre de recherche doit contenir "contrat"
    const input = mockedPage.getByPlaceholder(/rechercher dans vos documents/i)
    await expect(input).toHaveValue('contrat', { timeout: 2000 })
  })
})
