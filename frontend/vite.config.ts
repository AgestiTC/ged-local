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
    port: 5173,
    proxy: {
      // Proxy vers le backend en développement
      '/api': {
        target: 'http://localhost:8000',
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
