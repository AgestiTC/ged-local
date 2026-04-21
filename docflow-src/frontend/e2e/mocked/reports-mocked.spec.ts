/**
 * Tests E2E mockés — Page Rapports avec API simulée
 * ==================================================
 * Ces tests fonctionnent SANS backend réel grâce aux mocks API.
 * Idéal pour CI/CD.
 */

import { test, expect, MOCK_DOCUMENTS } from '../fixtures'

test.describe('Page Rapports — avec documents (API mockée)', () => {
  test.beforeEach(async ({ mockedPage }) => {
    await mockedPage.goto('/')
    await mockedPage.waitForLoadState('networkidle')
  })

  test('les documents mockés s\'affichent dans la liste', async ({ mockedPage }) => {
    // Les documents doivent apparaître dans le FileExplorer
    await expect(
      mockedPage.getByText('rapport_annuel_2025.pdf').or(
        mockedPage.getByText(MOCK_DOCUMENTS[0].nom)
      ).first()
    ).toBeVisible({ timeout: 5000 })
  })

  test('un document sélectionné incrémente le compteur', async ({ mockedPage }) => {
    // Cliquer sur la checkbox ou la carte du premier document
    const firstDoc = mockedPage.getByText(MOCK_DOCUMENTS[0].nom).first()
    await firstDoc.waitFor({ state: 'visible', timeout: 5000 })
    await firstDoc.click()

    // Le compteur de sélection doit indiquer 1
    await expect(
      mockedPage.getByText(/1 sélectionné/i).or(mockedPage.getByText(/1 document/i)).first()
    ).toBeVisible({ timeout: 2000 })
  })

  test('le bouton générer s\'active avec document + prompt', async ({ mockedPage }) => {
    // Sélectionner un document
    const firstDoc = mockedPage.getByText(MOCK_DOCUMENTS[0].nom).first()
    await firstDoc.waitFor({ state: 'visible', timeout: 5000 })
    await firstDoc.click()

    // Saisir un prompt
    await mockedPage.getByPlaceholder(/rapport à générer/i).fill('Fais une synthèse de ce document.')

    // Le bouton générer doit maintenant être actif
    const generateBtn = mockedPage.getByRole('button', { name: /générer/i })
    await expect(generateBtn).toBeEnabled({ timeout: 2000 })
  })

  test('tout sélectionner / tout désélectionner', async ({ mockedPage }) => {
    // Chercher le bouton "Tout sélectionner"
    const selectAllBtn = mockedPage.getByRole('button', { name: /tout sélectionner/i })
    await selectAllBtn.waitFor({ state: 'visible', timeout: 5000 })

    await selectAllBtn.click()

    // Le compteur doit afficher le nombre total
    await expect(
      mockedPage.getByText(new RegExp(`${MOCK_DOCUMENTS.length} sélectionné`, 'i'))
    ).toBeVisible({ timeout: 2000 })

    // Tout désélectionner
    await mockedPage.getByRole('button', { name: /tout désélectionner/i }).click()
    await expect(
      mockedPage.getByText(/0 sélectionné/i).or(mockedPage.getByText(/aucun document sélectionné/i)).first()
    ).toBeVisible({ timeout: 2000 })
  })
})

test.describe('ReportPreview — affichage rapport', () => {
  test.beforeEach(async ({ mockedPage }) => {
    await mockedPage.goto('/')
    await mockedPage.waitForLoadState('networkidle')
  })

  test('la colonne résultat montre un état vide au départ', async ({ mockedPage }) => {
    // Sans rapport généré, un état vide doit être visible
    await expect(
      mockedPage.getByText(/aucun rapport/i).or(
        mockedPage.getByText(/génère un rapport/i).or(
          mockedPage.getByText(/en attente/i)
        )
      ).first()
    ).toBeVisible({ timeout: 3000 })
  })
})
