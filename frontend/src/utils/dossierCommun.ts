/**
 * Dossier commun des documents d'un candidat (12/10/2026) — sert à « Resynchroniser avec son
 * dossier » : retrouver TOUS les documents indexés de ce dossier (un 13e fichier manquait dans le
 * candidat, et il fallait supprimer puis recréer le candidat). Fonction PURE.
 *
 * Rend le plus long préfixe de DOSSIERS commun aux chemins (sans le nom de fichier), ou null s'il
 * est trop haut pour désigner un candidat (moins de PROFONDEUR_MIN dossiers sous l'hôte/partage) —
 * resynchroniser depuis la racine du NAS aspirerait tout.
 */
const PROFONDEUR_MIN = 2

export function dossierCommun(chemins: string[]): string | null {
  const dossiers = chemins
    .filter(Boolean)
    .map(c => c.replace(/\\/g, '/').split('/').slice(0, -1))   // sans le nom de fichier
  if (!dossiers.length) return null
  const commun: string[] = []
  for (let i = 0; i < Math.min(...dossiers.map(d => d.length)); i++) {
    const seg = dossiers[0][i]
    if (dossiers.every(d => d[i] === seg)) commun.push(seg)
    else break
  }
  // « smb://hote/partage/… » → ['smb:', '', 'hote', 'partage', …] : on compte les dossiers APRÈS le partage.
  const debut = commun[0]?.endsWith(':') ? 4 : 1
  if (commun.length - debut < PROFONDEUR_MIN) return null
  return commun.join('/')
}

/**
 * Nom de candidat tiré d'un dossier : son dernier segment, sans préfixe générique
 * (« OFFRE_CES » → « CES », « Offre - Durand SA » → « Durand SA »), « _ » → espace.
 */
export function nomCandidat(dossier: string | null): string {
  const dernier = (dossier ?? '').replace(/\\/g, '/').split('/').filter(Boolean).pop() ?? ''
  const nettoye = dernier.replace(/^(offres?|candidats?|dossiers?|lot\s*\d+)[\s_\-–:.]+/i, '').replace(/_/g, ' ').trim()
  return nettoye || dernier
}

/** `nom`, ou « nom (2) », « nom (3) »… s'il est déjà pris (comparaison sans casse). */
export function nomUnique(nom: string, existants: string[]): string {
  const pris = new Set(existants.map(n => n.trim().toLowerCase()))
  if (!pris.has(nom.toLowerCase())) return nom
  let i = 2
  while (pris.has(`${nom} (${i})`.toLowerCase())) i++
  return `${nom} (${i})`
}
