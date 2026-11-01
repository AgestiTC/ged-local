/**
 * Garde statique — aucun appel à une route ADMIN au chargement d'une page ouverte au rôle utilisateur
 * ==================================================================================================
 * `systemApi.getConfig / models / services` lisent /api/system/* (admin, services/acces.py). Un composant
 * monté sur une page « utilisateur » (/, /ged, /dossiers, /regroupements…) qui les appelle sans passer
 * par `estAdmin` ferait un 403 au chargement pour Marie-Laure. Les pages et dossiers réservés aux admins
 * (Paramètres, Journaux…) sont exemptés : le rôle utilisateur n'y entre pas (MainLayout).
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const RACINE = join(__dirname, '..', '..')   // src/
// /api/sources/* est admin aussi (identifiants SMB, indexation) : la GED et les arbres de fichiers,
// ouverts au rôle utilisateur, l'appelaient au chargement (constaté en pile jetable le 31/10/2026).
const APPEL_ADMIN = /(systemApi\.(getConfig|models|services|diagnosticIA|iaEchecs|antivirus)|sourcesApi\.(list|dossiersSurveilles|indexed|progression))\s*\(/

// Pages et composants que seul un admin ouvre (cf. cheminReserveAdmin et les sections de Paramètres).
// PAS components/ged/ en bloc : la GED est ouverte au rôle utilisateur.
const EXEMPTES = [
  'pages/SettingsPage.tsx', 'pages/LogsPage.tsx', 'pages/DuplicatesPage.tsx', 'pages/ReorganizePage.tsx',
  'pages/HuggingFacePage.tsx', 'components/settings/', 'components/logs/',
  'components/ged/SourcesManager.tsx', 'components/ged/ScannersManager.tsx', 'components/ged/IndexedSourcesSummary.tsx',
  'components/ged/IndexedFolders.tsx',   // monté seulement par les deux précédents
  'api/', '__tests__/',
]

function fichiers(dir: string): string[] {
  return readdirSync(dir).flatMap(n => {
    const p = join(dir, n)
    return statSync(p).isDirectory() ? fichiers(p) : /\.(tsx?|jsx?)$/.test(n) ? [p] : []
  })
}

describe('appels admin au chargement', () => {
  const fautifs = fichiers(RACINE)
    .map(f => relative(RACINE, f).replace(/\\/g, '/'))
    .filter(f => !EXEMPTES.some(e => f.startsWith(e) || f === e))
    .filter(f => APPEL_ADMIN.test(readFileSync(join(RACINE, f), 'utf-8')))
    .filter(f => !readFileSync(join(RACINE, f), 'utf-8').includes('estAdmin'))

  it('tout fichier qui lit la config, les modèles ou les services passe par estAdmin', () => {
    expect(fautifs).toEqual([])
  })
})
