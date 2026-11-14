/**
 * Lien porté par une notification (cloche, étape 11 du rangement) : on ne suit qu'une page de
 * l'application (« /rangement?onglet=plan »), jamais une adresse extérieure ni « //hôte » (qui en
 * serait une).
 */
export function lienInterne(lien: string | null | undefined): string | null {
  return lien && lien.startsWith('/') && !lien.startsWith('//') ? lien : null
}
