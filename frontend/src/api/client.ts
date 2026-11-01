/**
 * Client API — DocFlow AI
 * ========================
 * Client axios centralisé avec intercepteurs pour les erreurs.
 * Toutes les requêtes passent par ce client.
 */

import axios from 'axios'

// Si VITE_API_URL est vide ("") → proxy nginx → URLs relatives (Synology / production)
// Si VITE_API_URL est défini → URL absolue (dev local ou surcharge explicite)
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// Gestion de l'authentification (étape 3 du plan) : le store s'enregistre ici au chargement. Passer par un
// registre évite l'import circulaire client → store → api → client.
export const DETAIL_ADMIN_SEULEMENT = 'Réservé aux administrateurs'   // message du serveur (services/acces.py)
export interface GestionnairesAuth {
  sur401: () => void
  sur403Admin: () => void
}
let gestionnairesAuth: GestionnairesAuth | null = null
export function definirGestionnairesAuth(g: GestionnairesAuth | null): void {
  gestionnairesAuth = g
}

/** 401 → l'écran de connexion prend la main ; 403 « admin » → un avis (une fois). L'erreur est relancée telle quelle. */
function surReponseEnErreur(error: { response?: { status?: number; data?: { detail?: unknown } } }): void {
  const status = error?.response?.status
  if (status === 401) gestionnairesAuth?.sur401()
  else if (status === 403 && error.response?.data?.detail === DETAIL_ADMIN_SEULEMENT) gestionnairesAuth?.sur403Admin()
}

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
    surReponseEnErreur(error)
    return Promise.reject(error)
  }
)

// Client avec timeout long pour la génération (Mixtral est lent)
export const apiClientLong = axios.create({
  baseURL: `${API_URL}/api`,
  headers: { 'Content-Type': 'application/json' },
  timeout: 600_000,  // 10 minutes pour Mixtral
})

apiClientLong.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || 'Erreur inconnue'
    console.error('[API Error (long)]', error.config?.url, message)
    surReponseEnErreur(error)
    return Promise.reject(error)
  }
)
