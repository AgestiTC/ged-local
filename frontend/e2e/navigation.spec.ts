/**
 * Tests E2E — Navigation & Layout
 * =================================
 * Vérifie que la navigation entre les pages fonctionne
 * et que le layout de base est présent.
 *
 * Ces tests ne nécessitent pas de backend actif (pas d'appels API bloquants).
 */

import { test, expect } from '@playwright/test'

test.describe('Navigation principale', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('la page rapports est la page par défaut', async ({ page }) => {
    // L'URL doit être / ou /reports
    await expect(page).toHaveURL(/\/$|\/reports/)
    // Le titre de la page doit contenir DocFlow
    await expect(page).toHaveTitle(/DocFlow/)
  })

  test('la sidebar est présente avec les liens de navigation', async ({ page }) => {
    // Les liens de navigation doivent être visibles
    await expect(page.getByRole('link', { name: /rapports/i })).toBeVisible()
    await expect(page.getByRole('link', { name: /ged/i })).toBeVisible()
    await expect(page.getByRole('link', { name: /paramètres/i })).toBeVisible()
  })

  test('naviguer vers la page GED', async ({ page }) => {
    await page.getByRole('link', { name: /ged/i }).click()
    await expect(page).toHaveURL(/\/ged/)
    // La barre de recherche doit être présente
    await expect(page.getByPlaceholder(/rechercher/i)).toBeVisible()
  })

  test('naviguer vers la page paramètres', async ({ page }) => {
    await page.getByRole('link', { name: /paramètres/i }).click()
    await expect(page).toHaveURL(/\/settings/)
  })

  test('retourner à la page rapports depuis GED', async ({ page }) => {
    await page.goto('/ged')
    await page.getByRole('link', { name: /rapports/i }).click()
    await expect(page).toHaveURL(/\/$|\/reports/)
  })
})

test.describe('Page Rapports — layout', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('trois colonnes sont visibles', async ({ page }) => {
    // Colonne gauche : fichiers
    await expect(page.getByText(/documents/i).first()).toBeVisible()

    // Colonne centre : éditeur de prompt
    const promptArea = page.getByPlaceholder(/rapport à générer/i)
    await expect(promptArea).toBeVisible()

    // Sélecteur de modèle
    await expect(page.getByText(/mixtral/i).first()).toBeVisible()
  })

  test('zone drag & drop est présente', async ({ page }) => {
    // La zone de drop doit exister (DropZone)
    await expect(
      page.getByText(/glisser.*fichiers/i).or(page.getByText(/déposer/i)).first()
    ).toBeVisible()
  })

  test('le bouton générer est désactivé sans sélection', async ({ page }) => {
    // Sans document sélectionné ni prompt, le bouton doit être désactivé
    const generateBtn = page.getByRole('button', { name: /générer/i })
    await expect(generateBtn).toBeDisabled()
  })

  test('le sélecteur de mode de sortie fonctionne', async ({ page }) => {
    // Les modes doivent être présents
    await expect(page.getByText(/rapport libre/i)).toBeVisible()
    await expect(page.getByText(/remplir.*template/i)).toBeVisible()
    await expect(page.getByText(/classement/i)).toBeVisible()
  })

  test('sélectionner le mode template affiche la zone d\'upload', async ({ page }) => {
    // Cliquer sur "Remplir un template"
    await page.getByText(/remplir.*template/i).click()
    // La zone d'upload template doit apparaître
    await expect(page.getByText(/template docx/i)).toBeVisible()
  })
})

test.describe('Page GED — layout', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/ged')
  })

  test('barre de recherche avec modes', async ({ page }) => {
    await expect(page.getByPlaceholder(/rechercher dans vos documents/i)).toBeVisible()
    await expect(page.getByRole('button', { name: /rechercher/i })).toBeVisible()
  })

  test('filtres de mode de recherche présents', async ({ page }) => {
    await expect(page.getByText('Hybride')).toBeVisible()
    await expect(page.getByText('Texte')).toBeVisible()
    await expect(page.getByText('Sémantique')).toBeVisible()
  })

  test('état vide avec message d\'aide', async ({ page }) => {
    // Sans recherche, un message d'aide doit être visible
    await expect(
      page.getByText(/recherche hybride/i).or(page.getByText(/importez des documents/i))
    ).toBeVisible()
  })

  test('le bouton rechercher est désactivé si la requête est vide', async ({ page }) => {
    const searchBtn = page.getByRole('button', { name: /rechercher/i })
    await expect(searchBtn).toBeDisabled()
  })

  test('remplir la barre de recherche active le bouton', async ({ page }) => {
    await page.getByPlaceholder(/rechercher dans vos documents/i).fill('contrat')
    const searchBtn = page.getByRole('button', { name: /rechercher/i })
    await expect(searchBtn).toBeEnabled()
  })
})

test.describe('Page Paramètres — layout', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/settings')
  })

  test('sections principales présentes', async ({ page }) => {
    await expect(page.getByText(/dossiers surveillés/i)).toBeVisible()
    await expect(page.getByText(/services/i).first()).toBeVisible()
  })

  test('formulaire d\'ajout de dossier présent', async ({ page }) => {
    // Le champ pour entrer un chemin de dossier doit être présent
    await expect(page.getByPlaceholder(/chemin absolu/i)).toBeVisible()
  })
})
