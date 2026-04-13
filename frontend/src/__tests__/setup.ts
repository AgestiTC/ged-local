/**
 * Setup vitest — DocFlow AI
 * ==========================
 * Initialise l'environnement de test jsdom.
 * Ce fichier est exécuté avant chaque fichier de test.
 */

import { vi } from 'vitest'

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
