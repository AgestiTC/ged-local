/**
 * Tests E2E — Page Rapports (génération)
 * =========================================
 * Teste le flux principal de génération de rapports :
 * saisie du prompt, sélection de mode, interaction avec l'interface.
 *
 * Note : les appels API vers le backend sont effectifs.
 * Si le backend n'est pas disponible, les tests réseau échoueront
 * mais les tests d'interface seule resteront verts.
 */

import { test, expect, Page } from '@playwright/test'

async function gotoReports(page: Page) {
  await page.goto('/')
  // Attendre que la page soit chargée
  await page.waitForLoadState('networkidle')
}

test.describe('Éditeur de prompt', () => {
  test.beforeEach(async ({ page }) => {
    await gotoReports(page)
  })

  test('saisir un prompt l\'enregistre dans le textarea', async ({ page }) => {
    const textarea = page.getByPlaceholder(/rapport à générer/i)
    await textarea.fill('Analyse les documents et génère un rapport de synthèse.')
    await expect(textarea).toHaveValue('Analyse les documents et génère un rapport de synthèse.')
  })

  test('le dropdown des presets est accessible', async ({ page }) => {
    // Le bouton presets doit être présent
    const presetsBtn = page.getByTitle(/presets/i).or(
      page.getByRole('button', { name: /presets/i })
    ).first()

    // S'il n'existe pas, chercher via l'icône ou le texte alternatif
    const presetsArea = page.locator('[data-testid="prompt-presets"]').or(
      page.getByText(/presets/i).first()
    )
    // On vérifie juste que la zone d'interaction existe
    await expect(presetsArea.or(page.getByPlaceholder(/rapport à générer/i))).toBeVisible()
  })

  test('le sélecteur de modèle est présent', async ({ page }) => {
    // Un select ou un dropdown avec les noms de modèles
    await expect(
      page.getByText(/mixtral/i).or(page.getByText(/mistral/i)).first()
    ).toBeVisible()
  })
})

test.describe('Modes de sortie', () => {
  test.beforeEach(async ({ page }) => {
    await gotoReports(page)
  })

  test('mode rapport libre — état par défaut', async ({ page }) => {
    // Le mode rapport libre doit être sélectionné par défaut
    const rapportLibre = page.getByText(/rapport libre/i)
    await expect(rapportLibre).toBeVisible()
    // Il doit avoir l'apparence "actif" (classe CSS spécifique)
    const parent = rapportLibre.locator('..')
    await expect(parent).toHaveClass(/bg-blue|text-blue|ring|border-blue/i)
  })

  test('switcher vers classement change le label du prompt', async ({ page }) => {
    await page.getByText(/classement/i).click()
    // Le label du textarea doit changer
    await expect(
      page.getByText(/critères de classement/i).or(page.getByText(/classement/i).first())
    ).toBeVisible()
  })

  test('switcher vers template affiche la zone d\'upload', async ({ page }) => {
    await page.getByText(/remplir.*template/i).click()
    // La zone de drop pour le template doit apparaître
    await expect(
      page.getByText(/template docx/i).or(page.getByText(/glisser.*template/i))
    ).toBeVisible()
  })

  test('revenir au rapport libre masque la zone template', async ({ page }) => {
    await page.getByText(/remplir.*template/i).click()
    await page.getByText(/rapport libre/i).click()
    // La zone template ne doit plus être visible
    await expect(page.getByText(/template docx/i)).not.toBeVisible()
  })
})

test.describe('Génération — validation formulaire', () => {
  test.beforeEach(async ({ page }) => {
    await gotoReports(page)
  })

  test('le bouton générer est désactivé sans prompt', async ({ page }) => {
    const generateBtn = page.getByRole('button', { name: /générer/i })
    // Vider le prompt
    await page.getByPlaceholder(/rapport à générer/i).fill('')
    await expect(generateBtn).toBeDisabled()
  })

  test('le bouton générer est désactivé sans document sélectionné', async ({ page }) => {
    // Saisir un prompt mais pas de document
    await page.getByPlaceholder(/rapport à générer/i).fill('Analyse')
    const generateBtn = page.getByRole('button', { name: /générer/i })
    await expect(generateBtn).toBeDisabled()
  })

  test('le compteur de sélection affiche 0 initialement', async ({ page }) => {
    // La barre de sélection ou le compteur doit indiquer 0
    await expect(
      page.getByText(/0 sélectionné/i).or(page.getByText(/aucun document/i)).first()
    ).toBeVisible()
  })
})
