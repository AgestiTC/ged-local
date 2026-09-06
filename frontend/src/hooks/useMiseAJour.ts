/**
 * Détecte qu'une nouvelle version de Matothèque est en ligne pendant que l'onglet, lui,
 * tourne encore sur l'ancienne.
 *
 * Le problème n'est pas le cache HTTP — le nginx du frontend sert déjà `index.html` en
 * `no-cache` et les bundles hashés en `immutable`, donc un simple rechargement suffit à
 * prendre la nouvelle version. Le problème est qu'un onglet resté ouvert n'a **aucune
 * raison de recharger** : il continue d'exécuter le bundle d'hier, indéfiniment.
 *
 * On surveille donc DEUX choses, parce qu'elles ne bougent pas ensemble :
 *
 * - **la version du backend** (`/api/version`) — change à chaque déploiement d'image
 *   backend ;
 * - **le nom du bundle d'entrée** dans `index.html` (`/assets/index-<hash>.js`) — c'est
 *   le seul signal qui attrape un frontend rebuild **sans** changement de version, cas
 *   réel quand on republie le tag `latest`.
 *
 * Ne déclenche JAMAIS le rechargement lui-même : il jetterait une saisie en cours. Le
 * bandeau propose, l'utilisateur dispose.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { systemApi } from '../api'

/** Extrait `/assets/index-<hash>.js` d'un HTML. `null` si absent (serveur de dev Vite). */
function bundleDe(html: string): string | null {
  return html.match(/\/assets\/index-[A-Za-z0-9_-]+\.js/)?.[0] ?? null
}

/** Bundle réellement chargé par CET onglet, lu dans le DOM au démarrage. */
function bundleCourant(): string | null {
  const src = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/"]')?.src
  return src ? bundleDe(src) : null
}

/** Toutes les 5 min : assez pour prévenir vite, assez peu pour ne pas marteler le serveur. */
const PERIODE_MS = 5 * 60 * 1000
/** Anti-rafale sur les retours d'onglet (alt-tab répétés). */
const MIN_ENTRE_SONDES_MS = 60 * 1000

export interface MiseAJour {
  /** Une version différente de celle de cet onglet est servie. */
  disponible: boolean
  /** Version annoncée par le backend, quand elle a changé. */
  version: string | null
}

export function useMiseAJour(): MiseAJour {
  const [etat, setEtat] = useState<MiseAJour>({ disponible: false, version: null })
  // Références de départ : c'est à ELLES qu'on compare, jamais au sondage précédent —
  // sinon deux déploiements successifs se neutraliseraient.
  //
  // Le bundle est lu dans le DOM, donc c'est bien « ce que CET onglet exécute ». La version
  // backend, elle, ne peut venir que du premier sondage : rien ne l'injecte dans la page
  // (pas de rendu serveur ici). Il reste donc une fenêtre — un déploiement qui tombe entre
  // le chargement de la page et le premier sondage passerait inaperçu côté version.
  // Ce n'est pas grave : ce déploiement-là aura changé le bundle, et c'est cette
  // comparaison-là qui fait foi. Écart signalé par la session FOULÉE, qui compare à un
  // `<meta app-version>` rendu par le serveur — possible chez elle (Jinja2), pas ici.
  const versionInitiale = useRef<string | null>(null)
  const bundleInitial = useRef<string | null>(bundleCourant())
  const derniereSonde = useRef(0)

  const sonder = useCallback(async () => {
    if (Date.now() - derniereSonde.current < MIN_ENTRE_SONDES_MS) return
    derniereSonde.current = Date.now()

    let versionServeur: string | null = null
    try {
      versionServeur = (await systemApi.version()).version
    } catch { /* backend qui redémarre : ce n'est pas une mise à jour, c'est une panne */ }

    let bundleServeur: string | null = null
    try {
      // `no-store` : on veut l'index.html du serveur, pas celui que le navigateur a gardé.
      const html = await fetch('/index.html', { cache: 'no-store' }).then(r => r.ok ? r.text() : '')
      bundleServeur = bundleDe(html)
    } catch { /* idem */ }

    if (versionInitiale.current === null && versionServeur) versionInitiale.current = versionServeur
    if (bundleInitial.current === null && bundleServeur) bundleInitial.current = bundleServeur

    const versionChange = Boolean(versionServeur && versionInitiale.current && versionServeur !== versionInitiale.current)
    const bundleChange = Boolean(bundleServeur && bundleInitial.current && bundleServeur !== bundleInitial.current)

    if (versionChange || bundleChange) {
      setEtat({ disponible: true, version: versionChange ? versionServeur : null })
    }
  }, [])

  useEffect(() => {
    void sonder()
    const t = setInterval(() => void sonder(), PERIODE_MS)
    // Au retour sur l'onglet : c'est le moment où l'on vient justement de déployer et où
    // l'on rouvre la fenêtre pour vérifier.
    const auRetour = () => { if (document.visibilityState === 'visible') void sonder() }
    document.addEventListener('visibilitychange', auRetour)
    window.addEventListener('focus', auRetour)
    return () => {
      clearInterval(t)
      document.removeEventListener('visibilitychange', auRetour)
      window.removeEventListener('focus', auRetour)
    }
  }, [sonder])

  return etat
}
