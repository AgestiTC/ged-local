/**
 * Setup vitest — DocFlow AI
 * ==========================
 * Initialise l'environnement de test jsdom.
 * Ce fichier est exécuté avant chaque fichier de test.
 */

import { vi } from 'vitest'

// Mock React pour permettre l'appel des hooks hors composant (Zustand, tests unitaires)
vi.mock('react', async () => {
  const react = await vi.importActual<typeof import('react')>('react')
  const horsRendu = {
    useSyncExternalStore: (_subscribe: unknown, getSnapshot: () => unknown) => getSnapshot(),
    useCallback: <T>(fn: T) => fn,
    useRef: <T>(initial: T) => ({ current: initial }),
    useMemo: <T>(fn: () => T) => fn(),
    useEffect: () => {},
    // Appelé par Zustand après chaque lecture du store : hook de confort pour les devtools,
    // sans effet sur la valeur lue, mais le vrai exige un rendu en cours.
    useDebugValue: () => {},
  }
  // `default` est réécrit AUSSI, et ce n'est pas une précaution de style : `...react` réinjecte
  // le vrai module en export par défaut. Zustand, qui fait `import ReactExports from 'react'`
  // puis destructure, y reprenait donc les VRAIS hooks — les stubs ci-dessus ne servaient qu'aux
  // imports nommés, et l'appel hors composant échouait quand même.
  return {
    ...react,
    ...horsRendu,
    default: { ...(react as { default?: object }).default, ...horsRendu },
  }
})

// Zustand ne lit PLUS le store par le `useSyncExternalStore` de React, mais par le shim
// `use-sync-external-store/shim/with-selector.js` — un paquet à part, qui importe React de son
// côté et échappe donc au mock ci-dessus. Résultat : tout hook lisant un store avec sélecteur
// (`useGEDStore(s => …)`) plantait hors composant sur « Cannot read properties of null (reading
// 'useRef') », et deux suites entières (useSearch, useDocuments) étaient rouges sans rapport
// avec ce qu'elles vérifient. On rend ici la même chose que React rendrait : le sélecteur
// appliqué à l'instantané courant.
vi.mock('use-sync-external-store/shim/with-selector.js', () => ({
  default: {
    useSyncExternalStoreWithSelector: (
      _subscribe: unknown,
      getSnapshot: () => unknown,
      _getServerSnapshot: unknown,
      selecteur: (etat: unknown) => unknown,
    ) => selecteur(getSnapshot()),
  },
}))

// Simuler import.meta.env pour les tests
Object.defineProperty(import.meta, 'env', {
  value: {
    VITE_API_URL: 'http://localhost:8000',
    MODE: 'test',
    DEV: false,
    PROD: false,
  },
  writable: true,
})

// Simuler EventSource (non disponible dans jsdom)
class MockEventSource {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2

  url: string
  readyState: number = MockEventSource.CONNECTING
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onopen: ((event: Event) => void) | null = null

  constructor(url: string) {
    this.url = url
    this.readyState = MockEventSource.OPEN
  }

  close() {
    this.readyState = MockEventSource.CLOSED
  }

  // Méthode utilitaire pour les tests
  _emit(data: string) {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', { data }))
    }
  }
}

vi.stubGlobal('EventSource', MockEventSource)

// Simuler crypto.randomUUID
Object.defineProperty(globalThis, 'crypto', {
  value: {
    randomUUID: () => 'test-uuid-' + Math.random().toString(36).slice(2),
    getRandomValues: (arr: Uint8Array) => {
      for (let i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256)
      return arr
    },
  },
  writable: true,
})

// Silence les erreurs console dans les tests (sauf si explicitement inspectées)
vi.spyOn(console, 'error').mockImplementation(() => {})
vi.spyOn(console, 'warn').mockImplementation(() => {})
