/**
 * Accès & connexion — aides d'INTERFACE (plan d'authentification, étape 3)
 * ========================================================================
 * Le serveur est la seule barrière (services/acces.py) : ce module ne décide que de ce qu'on
 * AFFICHE (confort) et de l'adresse où envoyer la personne se connecter. Aucune valeur en dur :
 * l'adresse de connexion vient de `/api/auth/me` (origine de la redirect_uri OIDC).
 */

export type Role = 'admin' | 'utilisateur'

export interface AuthUtilisateur {
  id?: string                // identifiant de la fiche (pour se reconnaître dans la liste des personnes)
  identifiant: string | null
  nom: string | null
  email: string | null
  role: Role
}

/** L'accès de secours est-il EN COURS ? (échéance ISO dans le futur ; illisible ou échue = non). */
export function suspensionActive(iso: string | null | undefined): boolean {
  if (!iso) return false
  const t = Date.parse(iso)
  return Number.isFinite(t) && t > Date.now()
}

export interface EtatAcces {
  authActive: boolean
  utilisateur: AuthUtilisateur | null
  suspensionJusqua?: string | null
}

/**
 * Pages réservées aux admins, d'après `services/acces.py` (REGLES) : /settings → /api/system/*,
 * /logs → /api/logs/*, /doublons → /api/duplicates/*, /reorganiser → /api/organize/*,
 * /huggingface → /api/huggingface/*. À tenir alignée avec REGLES quand une page change de rôle.
 */
const CHEMINS_ADMIN = ['/settings', '/logs', '/doublons', '/reorganiser', '/huggingface']

export function cheminReserveAdmin(pathname: string): boolean {
  return CHEMINS_ADMIN.some(c => pathname === c || pathname.startsWith(c + '/'))
}

/**
 * Voit-on l'interface d'administration ? Oui quand l'authentification est éteinte (interface
 * identique à avant) ou suspendue sans identité (le serveur laisse alors tout passer).
 */
export function estAdmin(e: EtatAcces): boolean {
  if (!e.authActive) return true
  if (e.utilisateur) return e.utilisateur.role === 'admin'
  return suspensionActive(e.suspensionJusqua)
}

/** Faut-il montrer l'écran « Se connecter » ? Jamais tant que `/me` n'a pas répondu, ni si l'auth est éteinte. */
export function doitSeConnecter(
  s: EtatAcces & { charge: boolean; nonConnecte: boolean },
): boolean {
  if (!s.charge || !s.authActive) return false
  if (suspensionActive(s.suspensionJusqua)) return false   // accès de secours : le serveur laisse passer
  if (s.nonConnecte) return true
  return s.utilisateur === null
}

/** Chemin de retour après connexion : relatif au site, sans `auth_erreur` (pas de boucle). Le serveur revalide. */
export function retourDepuis(pathname: string, search: string): string {
  if (!pathname.startsWith('/') || pathname.startsWith('//') || pathname.includes('\\')
    // eslint-disable-next-line no-control-regex
    || /[\u0000-\u001f\u007f]/.test(pathname + search)) return '/'
  const p = new URLSearchParams(search)
  p.delete('auth_erreur')
  const q = p.toString()
  return q ? `${pathname}?${q}` : pathname
}

/** Origine `http(s)://hôte[:port]` d'une adresse, ou null (absente, autre schéma, illisible). */
function origineHttp(adresse: string | null | undefined): string | null {
  if (!adresse) return null
  try {
    const u = new URL(adresse)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.origin : null
  } catch { return null }
}

export interface EntreeConnexion {
  baseApi: string                       // ex. « /api » (apiClient.defaults.baseURL)
  adresseConnexion: string | null       // /api/auth/me → adresse_connexion
  protocole: string                     // window.location.protocol
  pathname: string
  search: string
}

/**
 * Où mène « Se connecter » ? Le cookie de liaison et la redirection SSO ne marchent que par la route
 * TLS : sur http:// avec une adresse https configurée, on y renvoie (même chemin de retour).
 */
export function urlConnexion(e: EntreeConnexion): { url: string; versRouteTls: boolean } {
  const retour = encodeURIComponent(retourDepuis(e.pathname, e.search))
  const tls = origineHttp(e.adresseConnexion)
  if (e.protocole === 'http:' && tls && tls.startsWith('https://')) {
    return { url: `${tls}/api/auth/login?retour=${retour}`, versRouteTls: true }
  }
  return { url: `${e.baseApi}/auth/login?retour=${retour}`, versRouteTls: false }
}

/** `end_session_endpoint` : on n'y navigue que s'il est en https (jamais javascript:, data:, http:). */
export function finSessionSure(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    return new URL(url).protocol === 'https:' ? url : null
  } catch { return null }
}

const MESSAGES_ERREUR: Record<string, string> = {
  acces_refuse: "Votre compte du NAS n'est dans aucun groupe autorisé (matotheque-admin ou matotheque-utilisateurs).",
  compte_bloque: "Votre accès à Matothèque a été bloqué par un administrateur.",
  etat_invalide: "La connexion n'a pas pu être vérifiée (lien déjà utilisé ou navigateur différent). Recommencez.",
  etat_expire: "La connexion a pris trop de temps. Recommencez.",
  sso_refuse: "Le service de connexion du NAS a refusé la demande.",
  non_configure: "La connexion n'est pas encore configurée (Paramètres › Authentification).",
  sso_indisponible: "Le service de connexion du NAS ne répond pas. Réessayez dans un instant.",
}

/** Message (français) pour un code `?auth_erreur=` ; jamais le code brut. null si aucun code. */
export function messageErreurAuth(code: string | null | undefined): string | null {
  if (!code) return null
  return MESSAGES_ERREUR[code] ?? "La connexion a échoué. Réessayez, ou voyez un administrateur."
}
