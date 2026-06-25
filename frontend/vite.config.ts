import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Correspond au paths "@/*" du tsconfig.json
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // host:true → écoute sur 0.0.0.0 (nécessaire en conteneur, OK en local)
    host: true,
    // Polling : indispensable pour le HMR en conteneur sur bind-mount Windows
    // (les événements fs de l'hôte ne remontent pas au watcher du conteneur).
    watch: { usePolling: true, interval: 300 },
    // port 5174 par défaut pour coexister avec NetSight (5173) ; surchargeable
    port: Number(process.env.VITE_PORT) || 5174,
    proxy: {
      // Cible du proxy /api : VITE_API_TARGET en conteneur (→ http://backend:8000),
      // sinon localhost:8000 en bare-metal.
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
    css: false,
    // Exclure les tests e2e Playwright (lancés séparément via `npm run test:e2e`)
    exclude: ['node_modules/**', 'e2e/**'],
    coverage: {
      reporter: ['text', 'lcov'],
      exclude: ['node_modules/', 'src/__tests__/'],
    },
  },
})
