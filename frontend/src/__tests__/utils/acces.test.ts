/**
 * Tests — utils/acces (confort d'interface selon le rôle, adresse de connexion)
 * =============================================================================
 * Le serveur reste la barrière : ces fonctions ne décident que de ce qu'on AFFICHE.
 */
import { describe, it, expect } from 'vitest'
import {
  suspensionActive, cheminReserveAdmin, estAdmin, urlConnexion, finSessionSure, messageErreurAuth, doitSeConnecter,
  retourDepuis,
} from '../../utils/acces'

const FUTUR = new Date(Date.now() + 3_600_000).toISOString()
const PASSE = new Date(Date.now() - 3_600_000).toISOString()

describe('suspensionActive', () => {
  it.each([[FUTUR, true], [PASSE, false], [null, false], [undefined, false], ['', false], ['pas une date', false]])(
    '%s', (v, attendu) => expect(suspensionActive(v as string | null | undefined)).toBe(attendu))
})

describe('estAdmin', () => {
  it('authentification éteinte : tout est visible, comme avant', () => {
    expect(estAdmin({ authActive: false, utilisateur: null })).toBe(true)
  })
  it('suspension de secours sans identité : tout est visible (le serveur laisse passer)', () => {
    expect(estAdmin({ authActive: true, utilisateur: null, suspensionJusqua: FUTUR })).toBe(true)
    expect(estAdmin({ authActive: true, utilisateur: null, suspensionJusqua: PASSE })).toBe(false)
  })
  it('actif : seul le rôle admin', () => {
    expect(estAdmin({ authActive: true, utilisateur: { identifiant: 'a', nom: 'A', email: null, role: 'admin' } })).toBe(true)
    expect(estAdmin({ authActive: true, utilisateur: { identifiant: 'u', nom: 'U', email: null, role: 'utilisateur' } })).toBe(false)
    expect(estAdmin({ authActive: true, utilisateur: null })).toBe(false)
  })
})

describe('cheminReserveAdmin', () => {
  it.each(['/settings', '/logs', '/doublons', '/reorganiser', '/huggingface', '/settings/', '/logs/xyz'])(
    '%s est réservé aux admins', (p) => expect(cheminReserveAdmin(p)).toBe(true))
  it.each(['/', '/ged', '/scans', '/regroupements', '/liens', '/dossiers', '/dossiers/devenir-parent', '/wiki', '/admin',
    '/settingsx', '/logsx'])(
    '%s reste ouvert au rôle utilisateur', (p) => expect(cheminReserveAdmin(p)).toBe(false))
})

describe('retourDepuis', () => {
  it('chemin + requête', () => expect(retourDepuis('/ged', '?q=a')).toBe('/ged?q=a'))
  it('retire auth_erreur pour ne pas boucler', () => {
    expect(retourDepuis('/', '?auth_erreur=acces_refuse')).toBe('/')
    expect(retourDepuis('/ged', '?q=a&auth_erreur=x')).toBe('/ged?q=a')
  })
  it('refuse un chemin « // » (redirection ouverte)', () => expect(retourDepuis('//evil.invalid', '')).toBe('/'))
  it('refuse un chemin qui ne commence pas par /', () => expect(retourDepuis('evil', '')).toBe('/'))
  it('refuse antislash et caractères de contrôle', () => {
    expect(retourDepuis('/a\\b', '')).toBe('/')
    expect(retourDepuis('/a\nb', '')).toBe('/')
  })
})

describe('urlConnexion', () => {
  const base = { baseApi: '/api', adresseConnexion: 'https://ged.test.invalid' }
  it('en https : même origine, avec retour encodé', () => {
    const r = urlConnexion({ ...base, protocole: 'https:', pathname: '/ged', search: '?q=ab&x=1' })
    expect(r.url).toBe('/api/auth/login?retour=' + encodeURIComponent('/ged?q=ab&x=1'))
    expect(r.versRouteTls).toBe(false)
  })
  it('en http avec adresse https : renvoie vers la route TLS + chemin courant', () => {
    const r = urlConnexion({ ...base, protocole: 'http:', pathname: '/dossiers/x', search: '' })
    expect(r.url).toBe('https://ged.test.invalid/api/auth/login?retour=' + encodeURIComponent('/dossiers/x'))
    expect(r.versRouteTls).toBe(true)
  })
  it('en http sans adresse configurée : reste sur place', () => {
    const r = urlConnexion({ baseApi: '/api', adresseConnexion: null, protocole: 'http:', pathname: '/', search: '' })
    expect(r.url).toBe('/api/auth/login?retour=%2F')
    expect(r.versRouteTls).toBe(false)
  })
  it('en http avec adresse http : reste sur place (rien à gagner)', () => {
    const r = urlConnexion({ baseApi: '/api', adresseConnexion: 'http://nas.test.invalid', protocole: 'http:', pathname: '/', search: '' })
    expect(r.versRouteTls).toBe(false)
    expect(r.url.startsWith('/api/auth/login')).toBe(true)
  })
  it('une adresse non http(s) est ignorée', () => {
    const r = urlConnexion({ baseApi: '/api', adresseConnexion: 'javascript:alert(1)', protocole: 'http:', pathname: '/', search: '' })
    expect(r.url.startsWith('/api/auth/login')).toBe(true)
  })
  it('une adresse avec chemin ou identifiants est ramenée à son origine', () => {
    const r = urlConnexion({ baseApi: '/api', adresseConnexion: 'https://u:p@ged.test.invalid/x?y', protocole: 'http:', pathname: '/', search: '' })
    expect(r.url.startsWith('https://ged.test.invalid/api/auth/login?retour=')).toBe(true)
  })
})

describe('finSessionSure', () => {
  it('https accepté', () => expect(finSessionSure('https://sso.test.invalid/logout')).toBe('https://sso.test.invalid/logout'))
  it.each([null, undefined, '', 'http://sso.test.invalid/logout', 'javascript:alert(1)', 'data:text/html,x', '/relatif', 'pas une url'])(
    '%s refusé', (v) => expect(finSessionSure(v as string | null | undefined)).toBeNull())
})

describe('messageErreurAuth', () => {
  it.each(['acces_refuse', 'compte_bloque', 'etat_invalide', 'etat_expire', 'sso_refuse', 'non_configure', 'sso_indisponible'])(
    '%s : message français', (c) => expect(messageErreurAuth(c)).toMatch(/\S{4,}/))
  it('compte bloqué et accès refusé sont distincts', () => {
    expect(messageErreurAuth('compte_bloque')).not.toBe(messageErreurAuth('acces_refuse'))
  })
  it('code inconnu : message générique, jamais le code brut injecté', () => {
    const m = messageErreurAuth('<script>')
    expect(m).not.toContain('<script>')
    expect(m.length).toBeGreaterThan(5)
  })
  it('absent : null', () => expect(messageErreurAuth(null)).toBeNull())
})

describe('doitSeConnecter', () => {
  const user = { identifiant: 'u', nom: 'U', email: null, role: 'utilisateur' as const }
  it('chargement non terminé : non', () => {
    expect(doitSeConnecter({ charge: false, authActive: true, utilisateur: null, nonConnecte: false })).toBe(false)
  })
  it('éteinte : jamais, même après un 401 isolé', () => {
    expect(doitSeConnecter({ charge: true, authActive: false, utilisateur: null, nonConnecte: true })).toBe(false)
  })
  it('active sans personne : oui', () => {
    expect(doitSeConnecter({ charge: true, authActive: true, utilisateur: null, nonConnecte: false })).toBe(true)
  })
  it('active, connecté : non ; après un 401 : oui', () => {
    expect(doitSeConnecter({ charge: true, authActive: true, utilisateur: user, nonConnecte: false })).toBe(false)
    expect(doitSeConnecter({ charge: true, authActive: true, utilisateur: user, nonConnecte: true })).toBe(true)
  })
  it('suspension de secours sans personne : non (le serveur laisse passer)', () => {
    expect(doitSeConnecter({ charge: true, authActive: true, utilisateur: null, nonConnecte: false, suspensionJusqua: FUTUR })).toBe(false)
  })
  it('suspension en cours : même après un 401, non', () => {
    expect(doitSeConnecter({ charge: true, authActive: true, utilisateur: null, nonConnecte: true, suspensionJusqua: FUTUR })).toBe(false)
  })
  it('suspension échue sans personne : oui', () => {
    expect(doitSeConnecter({ charge: true, authActive: true, utilisateur: null, nonConnecte: false, suspensionJusqua: PASSE })).toBe(true)
  })
})
