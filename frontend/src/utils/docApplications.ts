/**
 * Doc des applications — fonctions pures (plan docs/plan-reception-doc-applications.md).
 */

/**
 * Transforme ce que l'admin colle (chemin Windows `\\NAS\partage\dossier`, `smb://…`, ou
 * `hôte/partage/dossier`) en PRÉFIXE de règle tel que la Matothèque enregistre les chemins SMB :
 * `smb://hôte/partage/dossier/` (toujours terminé par « / »).
 */
export function versPrefixe(saisie: string): string {
  let s = saisie.trim().replace(/\\/g, '/')
  if (!s) return ''
  if (/^smb:\/\//i.test(s)) s = s.slice(6)
  s = s.replace(/^\/+/, '').replace(/\/+$/, '')
  return s ? `smb://${s}/` : ''
}

/** « aujourd'hui », « hier », « il y a 12 jours » — `maintenant` injectable pour les tests. */
export function ageDepot(iso: string | null, maintenant: Date = new Date()): string {
  if (!iso) return 'jamais'
  const jours = Math.floor((maintenant.getTime() - new Date(iso).getTime()) / 86_400_000)
  if (jours <= 0) return "aujourd'hui"
  if (jours === 1) return 'hier'
  return `il y a ${jours} jours`
}

/** Tags saisis « a, b ; c » → ['a', 'b', 'c'] (sans vides ni doublons). */
export function lireTags(saisie: string): string[] {
  const out: string[] = []
  for (const t of saisie.split(/[,;]/).map(x => x.trim()).filter(Boolean)) {
    if (!out.includes(t)) out.push(t)
  }
  return out
}
