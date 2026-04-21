/**
 * Tests E2E — Page GED (Gestion Électronique de Documents)
 * =========================================================
 * Teste la recherche, les filtres, et le panneau latéral document.
 */

import { test, expect, Page } from '@playwright/test'

async function gotoGED(page: Page) {
  await page.goto('/ged')
  await page.waitForLoadState('networkidle')
}

test.describe('Barre de recherche', () => {
  test.beforeEach(async ({ page }) => {
    await gotoGED(page)
  })

  test('la recherche s\'active au Enter', async ({ page }) => {
    const input = page.getByPlaceholder(/rechercher dans vos documents/i)
    await input.fill('contrat')
    await input.press('Enter')

    // Soit des résultats, soit "aucun résultat"
    await page.waitForTimeout(1000)
    const hasResults = await page.getByText(/résultat/i).first().isVisible().catch(() => false)
    const hasEmpty = await page.getByText(/aucun résultat/i).isVisible().catch(() => false)
    const isLoading = await page.getByText(/recherche en cours/i).isVisible().catch(() => false)

    expect(hasResults || hasEmpty || isLoading).toBe(true)
  })

  test('le bouton effacer apparaît après une recherche', async ({ page }) => {
    const input = page.getByPlaceholder(/rechercher dans vos documents/i)
    await input.fill('test')
    await page.getByRole('button', { name: /rechercher/i }).click()

    // Le bouton effacer (×) doit apparaître
    await expect(
      page.getByRole('button', { name: /effacer/i }).or(
        page.locator('button[title="Effacer"]')
      ).first()
    ).toBeVisible({ timeout: 3000 })
  })

  test('effacer remet la recherche à zéro', async ({ page }) => {
    const input = page.getByPlaceholder(/rechercher dans vos documents/i)
    await input.fill('contrat')
    await page.getByRole('button', { name: /rechercher/i }).click()

    // Attendre le bouton effacer
    await page.waitForTimeout(500)
    const clearBtn = page.getByRole('button', { name: /effacer/i }).or(
      page.locator('button[title="Effacer"]')
    ).first()

    if (await clearBtn.isVisible()) {
      await clearBtn.click()
      await expect(input).toHaveValue('')
    }
  })
})

test.describe('Filtres de mode de recherche', () => {
  test.beforeEach(async ({ page }) => {
    await gotoGED(page)
  })

  test('sélectionner Texte change le mode', async ({ page }) => {
    await page.getByText('Texte').click()
    // Le bouton Texte doit être actif
    await expect(page.getByText('Texte')).toHaveClass(/bg-blue|text-blue|font-medium/i)
  })

  test('sélectionner Sémantique change le mode', async ({ page }) => {
    await page.getByText('Sémantique').click()
    await expect(page.getByText('Sémantique')).toHaveClass(/bg-blue|text-blue|font-medium/i)
  })

  test('revenir à Hybride', async ({ page }) => {
    await page.getByText('Texte').click()
    await page.getByText('Hybride').click()
    await expect(page.getByText('Hybride')).toHaveClass(/bg-blue|text-blue|font-medium/i)
  })
})

test.describe('Zone d\'import GED', () => {
  test.beforeEach(async ({ page }) => {
    await gotoGED(page)
  })

  test('la zone d\'import est présente dans la sidebar', async ({ page }) => {
    await expect(
      page.getByText(/importer/i).or(page.getByText(/glisser/i)).first()
    ).toBeVisible()
  })
})

test.describe('Panneau document (si résultats)', () => {
  test('le panneau s\'ouvre au clic sur un résultat', async ({ page }) => {
    await gotoGED(page)

    // Faire une recherche qui pourrait retourner des résultats
    const input = page.getByPlaceholder(/rechercher dans vos documents/i)
    await input.fill('document')
    await page.getByRole('button', { name: /rechercher/i }).click()

    // Attendre les résultats
    await page.waitForTimeout(2000)

    const firstResult = page.locator('.bg-white.border.rounded-lg').first()
    const hasResult = await firstResult.isVisible().catch(() => false)

    if (hasResult) {
      await firstResult.click()
      // Le panneau latéral doit s'ouvrir (w-80)
      await expect(page.locator('.w-80').first()).toBeVisible({ timeout: 3000 })
    } else {
      // Pas de résultats — test non applicable, passer
      test.skip()
    }
  })
})
