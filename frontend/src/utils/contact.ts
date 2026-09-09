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
 * Lien « Y aller » — passe l'adresse à l'application de navigation **du téléphone**.
 *
 * `geo:0,0?q=<adresse>` : Android propose le choix entre les applications installées (Maps,
 * OsmAnd, Organic Maps, Waze…). Rien ne part de Matothèque — c'est le système qui ouvre
 * l'application de l'utilisateur, sur un clic explicite, exactement comme s'il tapait
 * l'adresse lui-même.
 *
 * ⚠️ **Aucun repli vers un service de cartographie en ligne, et c'est délibéré.** La
 * première version renvoyait vers `openstreetmap.org` là où `geo:` n'est pas supporté — ce
 * qui revenait à **envoyer l'adresse du domicile d'une personne identifiée** à un site
 * tiers. Ce ne sont pas les données de l'utilisateur : ce sont celles de quelqu'un d'autre,
 * confiées pour un entretien. Hors plateforme supportée, on rend donc `null`, et l'écran
 * propose de **copier l'adresse** — même service rendu, rien de divulgué.
 * *(Décision du 09/09/2026, inscrite en ROADMAP avec le refus de la carte.)*
 */
export function lienCarte(adresse: string | null | undefined): string | null {
  if (!adresse) return null
  // `geo:` n'est honoré que par Android ; iOS et les navigateurs de bureau l'ignorent
  // silencieusement — proposer un lien mort serait pire que ne rien proposer.
  if (!/android/i.test(navigator.userAgent || '')) return null
  return `geo:0,0?q=${encodeURIComponent(adresse)}`
}
