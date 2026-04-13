/**
 * Playwright — Configuration des tests E2E DocFlow AI
 * ====================================================
 * Teste l'interface React contre un backend en cours d'exécution.
 * Lance le serveur Vite dev automatiquement si nécessaire.
 *
 * Usage :
 *   npm run test:e2e           # Tous les tests
 *   npm run test:e2e:ui        # UI interactive
 *   npx playwright test --headed  # Avec navigateur visible
 */

import { defineConfig, devices } from '@playwright/test'

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',

  // Délai global pour chaque test
  timeout: 30_000,
  // Délai pour expect()
  expect: { timeout: 5_000 },

  // Pas de parallélisme (évite les conflits de port devserver)
  fullyParallel: false,
  workers: 1,

  // Retenter les tests flaky en CI
  retries: process.env.CI ? 2 : 0,

  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],

  use: {
    baseURL: BASE_URL,
    // Screenshot en cas d'échec
    screenshot: 'only-on-failure',
    // Trace en cas d'échec (pour debug)
    trace: 'on-first-retry',
    // Langue française
    locale: 'fr-FR',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    // Décommenter pour tester sur d'autres navigateurs
    // { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    // { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],

  // Ignorer le dossier node_modules dans les tests
  testIgnore: ['**/node_modules/**'],

  // Lance le serveur Vite automatiquement pendant les tests
  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
