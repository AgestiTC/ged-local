/**
 * Liens de contact — téléphoner, ouvrir une carte
 * ===============================================
 * Ces helpers rendent des **URI**, pas des appels d'API navigateur. C'est ce qui les rend
 * utilisables ici : Matothèque est servie en **HTTP**, où `navigator.clipboard`,
 * `crypto.randomUUID` et consorts sont absents — mais `tel:` et `geo:` ne sont que des
 * schémas d'URL, que le système résout lui-même. Aucun contexte sécurisé requis, et
 * **aucune sortie réseau depuis l'application** : c'est l'OS qui ouvre l'appli, sur un clic.
 */

/**
 * `tel:` — l'OS ouvre son composeur (Téléphone sur mobile, Skype/Teams/Lync sur PC).
 *
 * ⚠️ **On coupe à la première annotation avant de nettoyer.** Une fiche remplie pendant un
 * appel contient « 06 12 34 56 78 (après 18 h) » ou « … à partir de 9h », et un simple
 * `replace(/\D/g, '')` recollerait les chiffres de la note au numéro : le lien composait
 * **061234567818**. Un mauvais numéro appelé est pire qu'un lien absent — d'où la coupure
 * au premier caractère qui ne peut pas appartenir à un numéro (lettre ou parenthèse).
 * *(Défaut trouvé par le test, pas à l'usage.)*
 */
export function lienTelephone(numero: string | null | undefined): string | null {
  if (!numero) return null
  const avantAnnotation = numero.split(/[([]|[a-zA-Zà-öø-ÿÀ-ÖØ-Þ]/)[0]
  const nettoye = avantAnnotation.replace(/[^\d+]/g, '')
  // Moins de 6 chiffres : ce n'est pas un numéro, c'est une note. Mieux vaut ne pas
  // proposer un lien qui ouvrirait le composeur sur rien.
  return nettoye.replace(/\D/g, '').length >= 6 ? `tel:${nettoye}` : null
}

/** Adresse exploitable pour une recherche cartographique (adresse + commune). */
export function adressePostale(...morceaux: (string | null | undefined)[]): string | null {
  const texte = morceaux.filter(Boolean).join(', ').trim()
  return texte.length >= 3 ? texte : null
}

/**
 * Lien « ouvrir dans une carte / un GPS », par ordre de ce qui marche vraiment :
 *
 * - **mobile** → `geo:0,0?q=<adresse>`. Android propose le choix entre les applications
 *   installées (Maps, OsmAnd, Organic Maps, Waze…) — c'est le seul schéma qui lance une
 *   **vraie application de navigation** plutôt qu'une page web.
 * - **ailleurs** (et iOS, qui ignore `geo:`) → **OpenStreetMap**, cohérent avec le reste du
 *   projet : pas de compte, pas de traceur, données libres.
 *
 * La détection se fait sur l'`userAgent`, ce qui est imparfait — mais l'échec est bénin :
 * au pire on ouvre une carte dans le navigateur au lieu d'une application. Un mauvais
 * diagnostic ne coûte donc rien, là où renoncer à `geo:` coûterait le geste demandé.
 */
export function lienCarte(adresse: string | null | undefined): string | null {
  if (!adresse) return null
  const q = encodeURIComponent(adresse)
  const mobile = /android|iphone|ipad|ipod|mobile/i.test(navigator.userAgent || '')
  const androidLike = /android/i.test(navigator.userAgent || '')
  if (mobile && androidLike) return `geo:0,0?q=${q}`
  return `https://www.openstreetmap.org/search?query=${q}`
}
