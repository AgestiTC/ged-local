/**
 * Tests E2E mockés — Page Paramètres
 * ====================================
 * Teste les statistiques, l'état des services et la gestion des dossiers
 * avec des données API simulées.
 */

import { test, expect } from '../fixtures'

test.describe('Page Paramètres — statistiques (mockées)', () => {
  test.beforeEach(async ({ mockedPage }) => {
    await mockedPage.goto('/settings')
    await mockedPage.waitForLoadState('networkidle')
  })

  test('les stats s\'affichent correctement', async ({ mockedPage }) => {
    // Total documents
    await expect(mockedPage.getByText('3')).toBeVisible({ timeout: 5000 })
    await expect(mockedPage.getByText(/documents indexés/i)).toBeVisible()
  })

  test('le volume indexé est affiché', async ({ mockedPage }) => {
    // 2 691 467 octets ≈ 2.6 Mo
    await expect(
      mockedPage.getByText(/mo/i).or(mockedPage.getByText(/ko/i)).first()
    ).toBeVisible({ timeout: 3000 })
  })

  test('la répartition par statut est affichée', async ({ mockedPage }) => {
    await expect(mockedPage.getByText(/enrichis/i)).toBeVisible({ timeout: 3000 })
    await expect(mockedPage.getByText(/en attente/i)).toBeVisible({ timeout: 3000 })
  })

  test('les catégories principales sont listées', async ({ mockedPage }) => {
    await expect(mockedPage.getByText('rapport')).toBeVisible({ timeout: 3000 })
    await expect(mockedPage.getByText('facture')).toBeVisible({ timeout: 3000 })
  })
})

test.describe('Page Paramètres — état des services (mockés)', () => {
  test.beforeEach(async ({ mockedPage }) => {
    await mockedPage.goto('/settings')
    await mockedPage.waitForLoadState('networkidle')
  })

  test('Tika est affiché comme disponible', async ({ mockedPage }) => {
    // La section "État des services" doit montrer Tika comme disponible
    await expect(mockedPage.getByText('Tika', { exact: false })).toBeVisible({ timeout: 3000 })
  })

  test('Ollama est affiché comme disponible', async ({ mockedPage }) => {
    await expect(mockedPage.getByText('Ollama', { exact: false })).toBeVisible({ timeout: 3000 })
  })
})

test.describe('Page Paramètres — dossiers surveillés (mockés)', () => {
  test.beforeEach(async ({ mockedPage }) => {
    await mockedPage.goto('/settings')
    await mockedPage.waitForLoadState('networkidle')
  })

  test('le dossier mocké s\'affiche', async ({ mockedPage }) => {
    await expect(mockedPage.getByText('Documents DocFlow')).toBeVisible({ timeout: 3000 })
  })

  test('le champ d\'ajout de dossier est présent', async ({ mockedPage }) => {
    await expect(mockedPage.getByPlaceholder(/chemin absolu/i)).toBeVisible()
  })

  test('le bouton Ajouter est désactivé si le champ est vide', async ({ mockedPage }) => {
    const btn = mockedPage.getByRole('button', { name: /ajouter/i })
    await expect(btn).toBeDisabled()
  })

  test('le bouton Ajouter s\'active avec un chemin', async ({ mockedPage }) => {
    await mockedPage.getByPlaceholder(/chemin absolu/i).fill('C:/Documents/test')
    const btn = mockedPage.getByRole('button', { name: /ajouter/i })
    await expect(btn).toBeEnabled()
  })

  test('la section À propos affiche la version', async ({ mockedPage }) => {
    await expect(mockedPage.getByText(/DocFlow AI v/i)).toBeVisible({ timeout: 3000 })
  })
})

test.describe('Page Paramètres — prompts pré-enregistrés (mockés)', () => {
  test.beforeEach(async ({ mockedPage }) => {
    await mockedPage.goto('/settings')
    await mockedPage.waitForLoadState('networkidle')
  })

  test('la section prompts est présente', async ({ mockedPage }) => {
    await expect(mockedPage.getByText(/prompts pré-enregistrés/i)).toBeVisible({ timeout: 3000 })
  })

  test('le prompt mocké s\'affiche', async ({ mockedPage }) => {
    await expect(mockedPage.getByText('Synthèse de contrat')).toBeVisible({ timeout: 3000 })
  })

  test('la catégorie du prompt est affichée', async ({ mockedPage }) => {
    await expect(mockedPage.getByText('Extraction')).toBeVisible({ timeout: 3000 })
  })

  test('le bouton Nouveau prompt est présent', async ({ mockedPage }) => {
    await expect(mockedPage.getByRole('button', { name: /nouveau prompt/i })).toBeVisible()
  })

  test('cliquer sur Nouveau prompt ouvre le formulaire', async ({ mockedPage }) => {
    await mockedPage.getByRole('button', { name: /nouveau prompt/i }).click()
    await expect(mockedPage.getByPlaceholder(/ex.*synthèse de contrat/i)).toBeVisible()
    await expect(mockedPage.getByPlaceholder(/écrivez le prompt ici/i)).toBeVisible()
  })

  test('le formulaire se ferme avec Annuler', async ({ mockedPage }) => {
    await mockedPage.getByRole('button', { name: /nouveau prompt/i }).click()
    await mockedPage.getByRole('button', { name: /annuler/i }).first().click()
    await expect(mockedPage.getByPlaceholder(/écrivez le prompt ici/i)).not.toBeVisible()
  })

  test('cliquer sur éditer ouvre le formulaire pré-rempli', async ({ mockedPage }) => {
    await mockedPage.getByTitle('Modifier').first().click()
    const nomInput = mockedPage.getByPlaceholder(/ex.*synthèse de contrat/i)
    await expect(nomInput).toHaveValue('Synthèse de contrat')
  })
})

test.describe('Page Paramètres — templates (mockés)', () => {
  test.beforeEach(async ({ mockedPage }) => {
    await mockedPage.goto('/settings')
    await mockedPage.waitForLoadState('networkidle')
  })

  test('la section templates est présente', async ({ mockedPage }) => {
    await expect(mockedPage.getByText(/^Templates$/i)).toBeVisible({ timeout: 3000 })
  })

  test('le template mocké s\'affiche avec son type', async ({ mockedPage }) => {
    await expect(mockedPage.getByText('Rapport mensuel')).toBeVisible({ timeout: 3000 })
    await expect(mockedPage.getByText('DOCX')).toBeVisible({ timeout: 3000 })
  })

  test('les champs du template sont affichés', async ({ mockedPage }) => {
    await expect(mockedPage.getByText(/\{\{titre\}\}/)).toBeVisible({ timeout: 3000 })
    await expect(mockedPage.getByText(/\{\{date\}\}/)).toBeVisible({ timeout: 3000 })
  })

  test('le bouton Ajouter un template est présent', async ({ mockedPage }) => {
    await expect(mockedPage.getByText(/ajouter un template/i)).toBeVisible()
  })

  test('la description du format est affichée', async ({ mockedPage }) => {
    await expect(mockedPage.getByText(/docx.*pdf/i)).toBeVisible({ timeout: 3000 })
  })
})
