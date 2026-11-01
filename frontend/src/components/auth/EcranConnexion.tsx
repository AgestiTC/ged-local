/**
 * Écran « Se connecter » — plein écran, affiché quand l'authentification est active et qu'aucune
 * session n'est ouverte (ou qu'un 401 est tombé). Un simple LIEN (navigation complète) vers
 * /api/auth/login, avec retour sur la page d'origine.
 *
 * Route HTTP du LAN : le cookie de liaison et la redirection SSO ne marchent que par la route TLS ;
 * si l'adresse de connexion (issue de /api/auth/me) est en https, le lien y renvoie.
 */
import { LogIn } from 'lucide-react'
import { apiClient } from '../../api/client'
import { useAuthStore } from '../../stores/authStore'
import { messageErreurAuth, urlConnexion } from '../../utils/acces'
import Logo from '../layout/Logo'

export default function EcranConnexion() {
  const adresseConnexion = useAuthStore(s => s.adresseConnexion)
  const sessionExpiree = useAuthStore(s => s.sessionExpiree)
  const { pathname, search, protocol } = window.location
  const { url, versRouteTls } = urlConnexion({
    baseApi: apiClient.defaults.baseURL ?? '/api', adresseConnexion, protocole: protocol, pathname, search,
  })
  const erreur = messageErreurAuth(new URLSearchParams(search).get('auth_erreur'))

  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm max-w-md w-full p-6 text-center space-y-4">
        <Logo size={48} className="mx-auto" />
        <h1 className="text-xl font-bold text-gray-800">Matothèque</h1>
        <p className="text-sm text-gray-600">Connectez-vous avec votre compte du NAS pour continuer.</p>
        {sessionExpiree && !erreur && (
          <p role="status" className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            Votre session a expiré, reconnectez-vous.
          </p>
        )}
        {erreur && (
          <p role="alert" className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{erreur}</p>
        )}
        {versRouteTls && (
          <p className="text-xs text-gray-500">
            Vous êtes sur l'adresse non chiffrée (http). La connexion passe par l'adresse sécurisée
            {' '}<strong>{adresseConnexion}</strong> : vous y serez renvoyé, puis ramené sur cette page.
          </p>
        )}
        <a href={url}
          className="inline-flex items-center justify-center gap-2 w-full px-4 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
          <LogIn size={16} /> Se connecter
        </a>
      </div>
    </main>
  )
}
