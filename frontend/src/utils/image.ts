/**
 * Préparer une photo avant envoi
 * ==============================
 * Une photo de téléphone pèse 4 à 6 Mo, et la fiche d'un intervenant se remplit **debout,
 * pendant la visite, au bout d'un VPN sur données mobiles**. La redimensionner avant l'envoi
 * fait passer le transfert de plusieurs mégaoctets à environ 150 Ko — c'est la différence
 * entre un envoi qui aboutit et un envoi qu'on abandonne.
 *
 * ## L'orientation, et pourquoi `createImageBitmap`
 *
 * Les clichés de téléphone portent leur rotation dans les métadonnées EXIF. Une balise
 * `<img>` la respecte, mais **un redimensionnement par canvas la perd** : on obtient un
 * portrait couché, systématiquement, sans que rien ne le signale.
 *
 * `createImageBitmap(blob, { imageOrientation: 'from-image' })` applique la rotation avant
 * de rendre l'image — c'est la seule façon d'éviter d'écrire un décodeur EXIF à la main pour
 * un problème que le navigateur sait résoudre.
 *
 * ## En cas d'échec, on n'invente rien
 *
 * Un HEIC d'iPhone n'est décodable ni par Chrome ni par Firefox : `createImageBitmap` échoue.
 * On rend alors le fichier **d'origine**, et c'est le serveur qui refuse avec un message
 * utile. Fabriquer un substitut ou échouer en silence donnerait une photo « enregistrée »
 * qu'on ne découvrirait cassée qu'en rouvrant la fiche.
 */

/** Côté long visé après redimensionnement. Largement assez pour un portrait de fiche. */
export const COTE_MAX = 1024

/** Qualité JPEG. 0,85 : l'œil ne voit pas la différence, le poids est divisé par plus de dix. */
export const QUALITE = 0.85

/**
 * Dimensions cibles en conservant les proportions. Une image **déjà plus petite** que la
 * limite est laissée telle quelle : l'agrandir ajouterait du poids sans ajouter de détail.
 *
 * Fonction pure, donc testable — c'est là que se logent les erreurs de proportion.
 */
export function dimensionsCibles(
  largeur: number, hauteur: number, max: number = COTE_MAX,
): { largeur: number; hauteur: number } {
  const cote = Math.max(largeur, hauteur)
  if (cote <= max || cote === 0) return { largeur, hauteur }
  const ratio = max / cote
  return { largeur: Math.round(largeur * ratio), hauteur: Math.round(hauteur * ratio) }
}

/**
 * Réduit la photo et la convertit en JPEG. Rend le fichier **d'origine** si le navigateur ne
 * sait pas la décoder (HEIC) ou si le canvas n'est pas disponible — voir l'en-tête.
 */
export async function preparerPhoto(fichier: File, max = COTE_MAX): Promise<File> {
  if (typeof createImageBitmap !== 'function') return fichier

  let image: ImageBitmap
  try {
    // `from-image` applique la rotation EXIF AVANT le dessin : sans lui, portrait couché.
    image = await createImageBitmap(fichier, { imageOrientation: 'from-image' })
  } catch {
    return fichier   // format non décodable : le serveur tranchera, avec un message clair
  }

  const { largeur, hauteur } = dimensionsCibles(image.width, image.height, max)
  const canvas = document.createElement('canvas')
  canvas.width = largeur
  canvas.height = hauteur
  const ctx = canvas.getContext('2d')
  if (!ctx) { image.close?.(); return fichier }
  ctx.drawImage(image, 0, 0, largeur, hauteur)
  image.close?.()

  const blob = await new Promise<Blob | null>(res => canvas.toBlob(res, 'image/jpeg', QUALITE))
  if (!blob) return fichier

  // Un redimensionnement qui ALOURDIT le fichier n'a aucun intérêt : ça arrive sur les
  // petites images déjà compressées, où le ré-encodage JPEG coûte plus qu'il ne gagne.
  if (blob.size >= fichier.size && fichier.type.startsWith('image/')) return fichier

  const base = fichier.name.replace(/\.[^.]+$/, '') || 'portrait'
  return new File([blob], `${base}.jpg`, { type: 'image/jpeg' })
}
