/**
 * Lien vers une page d'aide du wiki, trouvée par son TITRE (recherche BookStack) : aucun identifiant de
 * page figé dans le code, la page peut être déplacée ou republiée sans casser le lien.
 * Partagé par l'écran de connexion et le panneau de file IA.
 */
export function lienAideWiki(wikiUrl: string | null | undefined, titre: string): string | null {
  const base = (wikiUrl ?? '').trim().replace(/\/+$/, '')
  if (!base) return null
  // Guillemets : recherche de la phrase exacte, pas de chaque mot.
  return `${base}/search?term=${encodeURIComponent(`"${titre}"`)}`
}
