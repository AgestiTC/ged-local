/**
 * Temps restant d'un comparatif (04/11/2026, demande « un temps estimatif »).
 * Moyenne mesurée sur CETTE comparaison : (dernière fin − début du 1er candidat) / candidats traités,
 * multipliée par ceux qui restent. Elle tient compte d'elle-même de la concurrence GPU et du
 * modèle choisi ; aucune estimation tant qu'aucun candidat n'est fini (rien de mesuré).
 */
export function estimerRestantMs(debutCandidats: number | null, derniereFin: number | null,
  traites: number, total: number): number | null {
  if (debutCandidats === null || derniereFin === null || traites === 0 || traites >= total) return null
  const moyenne = (derniereFin - debutCandidats) / traites
  return Math.max(0, moyenne * (total - traites))
}

/** « 45 s », « 3 min », « 1 h 05 ». */
export function dureeLisible(ms: number): string {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s} s`
  const min = Math.round(s / 60)
  if (min < 60) return `${min} min`
  return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, '0')}`
}
