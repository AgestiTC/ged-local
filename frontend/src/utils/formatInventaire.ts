/**
 * Mise en forme française de l'inventaire (Rangement) — tailles, nombres, variations, « il y a ».
 * Porté de rangement (`app/inventaire/format.py`) : mêmes conventions, mêmes résultats.
 *  - tailles en base 1024, comme l'explorateur de fichiers et WizTree : « 3,2 To », « 1,5 Ko » ;
 *  - virgule décimale, espace fine insécable entre les milliers : « 182 340 » ;
 *  - signe moins typographique (U+2212) : « −3 Mo ».
 */

const UNITES = ['o', 'Ko', 'Mo', 'Go', 'To', 'Po']
export const ESPACE_FINE = '\u202f'
export const MOINS = '\u2212'
export const INCONNU = '—'

export function tailleLisible(octets?: number | null): string {
  if (octets === null || octets === undefined) return INCONNU
  let valeur = octets
  let unite = 0
  while (valeur >= 1024 && unite < UNITES.length - 1) {
    valeur /= 1024
    unite += 1
  }
  if (unite === 0) return `${Math.trunc(valeur)} o`
  let texte = valeur.toFixed(1).replace('.', ',')
  if (texte.endsWith(',0')) texte = texte.slice(0, -2)
  return `${texte} ${UNITES[unite]}`
}

export function nombre(n?: number | null): string {
  if (n === null || n === undefined) return INCONNU
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ESPACE_FINE)
}

/** « +120 Go », « −3 Mo », « = » (aucun changement), « — » (pas de point de comparaison). */
export function variation(octets?: number | null): string {
  if (octets === null || octets === undefined) return INCONNU
  if (octets === 0) return '='
  return (octets > 0 ? '+' : MOINS) + tailleLisible(Math.abs(octets))
}

/** « 42 % » — espace insécable : le signe ne part jamais seul à la ligne. */
export function pourcent(n?: number | null): string {
  return n === null || n === undefined ? INCONNU : `${n}\u00a0%`
}

export function ilYa(iso: string | null | undefined, maintenant: Date = new Date()): string {
  if (!iso) return 'jamais'
  const secondes = Math.max(0, Math.floor((maintenant.getTime() - new Date(iso).getTime()) / 1000))
  if (secondes < 60) return "à l'instant"
  if (secondes < 3600) return `il y a ${Math.floor(secondes / 60)} min`
  if (secondes < 86400) return `il y a ${Math.floor(secondes / 3600)} h`
  return `il y a ${Math.floor(secondes / 86400)} j`
}

const STATUTS: Record<string, string> = {
  en_cours: 'en cours', termine: 'terminé', echec: 'en échec', interrompu: 'interrompu',
}

export function statutScan(statut?: string | null): string {
  return statut ? STATUTS[statut] ?? statut : 'jamais scanné'
}
