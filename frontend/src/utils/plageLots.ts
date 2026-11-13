/**
 * Plage horaire des lots IA (plan lots IA par modèle, étape 4) — fonctions PURES.
 * Les heures sont des « HH:MM », heure de Paris ; les deux vides = lots autorisés en permanence.
 * Le serveur revalide tout : ces contrôles ne servent qu'à dire l'erreur avant l'envoi.
 */

/** « HH:MM » valide (00:00 à 23:59) ? */
export function heureValide(v: string): boolean {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(v.trim())
}

/** Message d'erreur d'une plage saisie, ou null si elle est acceptable (complète, ou vide). */
export function erreurPlage(debut: string, fin: string): string | null {
  const d = debut.trim()
  const f = fin.trim()
  if (!d && !f) return null
  if (!d || !f) return "Indique l'heure de début ET l'heure de fin, ou laisse les deux vides."
  if (!heureValide(d) || !heureValide(f)) return 'Heure attendue au format HH:MM (ex. 22:00).'
  return null
}

/** Ce que la plage veut dire, en clair. */
export function libellePlage(debut: string, fin: string): string {
  const d = debut.trim()
  const f = fin.trim()
  if (!d || !f) return 'Toujours : les tâches de fond tournent à toute heure.'
  if (d === f) return 'Toute la journée (début = fin).'
  const nuit = d > f ? ' (jusqu\'au lendemain)' : ''
  return `De ${d} à ${f}${nuit}, heure de Paris. En dehors, les tâches de fond attendent ; « Créer », la discussion et la recherche restent servis.`
}
