/**
 * Client API — DocFlow AI
 * ========================
 * Client axios centralisé avec intercepteurs pour les erreurs.
 * Toutes les requêtes passent par ce client.
 */

import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: `${API_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30_000,  // 30s pour les requêtes normales
})

// Intercepteur erreurs : log + rethrow
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || 'Erreur inconnue'
    console.error('[API Error]', error.config?.url, message)
    return Promise.reject(error)
  }
)

// Client avec timeout long pour la génération (Mixtral est lent)
export const apiClientLong = axios.create({
  baseURL: `${API_URL}/api`,
  headers: { 'Content-Type': 'application/json' },
  timeout: 600_000,  // 10 minutes pour Mixtral
})
