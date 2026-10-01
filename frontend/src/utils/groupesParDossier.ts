/**
 * Regroupe des documents par candidat d'après leurs dossiers.
 *
 * Le candidat = le PREMIER dossier sous le dossier commun à tous les documents :
 *   …/TestIA/OFFRE_CES/OFFRE/1-AE.pdf  → « OFFRE_CES »
 *   …/TestIA/OFFRE_OTV/6.1-Mémoire.pdf → « OFFRE_OTV »
 * (le parent direct ne suffit pas : il vaudrait « OFFRE » pour CES). Un document posé
 * directement dans le dossier commun (la grille elle-même, une archive .zip) n'appartient à
 * aucun candidat : il est écarté et compté. Un préfixe partagé par tous les noms (« OFFRE_ »)
 * est retiré pour ne garder que « CES », « OTV ».
 */
export interface DocChemin {
  id: string
  chemin: string
}

export interface GroupeDossier {
  nom: string
  document_ids: string[]
}

const segments = (chemin: string): string[] =>
  chemin.replace(/\\/g, '/').replace(/^[a-z]+:\/\//i, '').split('/').filter(Boolean)

function prefixeCommun(noms: string[]): string {
  if (noms.length < 2) return ''
  let p = noms[0]
  for (const n of noms.slice(1)) {
    while (p && !n.startsWith(p)) p = p.slice(0, -1)
  }
  // On ne coupe qu'à un séparateur : « OFFRE_ » oui, « OF » (de OFFRE/OFFICE) non.
  const coupe = Math.max(p.lastIndexOf('_'), p.lastIndexOf('-'), p.lastIndexOf(' '))
  return coupe >= 0 ? p.slice(0, coupe + 1) : ''
}

export function groupesParDossier(docs: DocChemin[]): { groupes: GroupeDossier[]; ecartes: number } {
  const parties = docs.map(d => ({ id: d.id, segs: segments(d.chemin) }))
  if (parties.length === 0) return { groupes: [], ecartes: 0 }

  // Dossier commun = plus long préfixe de segments partagé (le nom de fichier exclu).
  let commun = parties[0].segs.length - 1
  for (const { segs } of parties.slice(1)) {
    let i = 0
    while (i < commun && i < segs.length - 1 && segs[i] === parties[0].segs[i]) i++
    commun = i
  }

  const parNom = new Map<string, string[]>()
  let ecartes = 0
  for (const { id, segs } of parties) {
    if (segs.length - 1 <= commun) { ecartes++; continue }   // fichier posé dans le dossier commun
    const nom = segs[commun]
    parNom.set(nom, [...(parNom.get(nom) ?? []), id])
  }

  const noms = [...parNom.keys()]
  const prefixe = prefixeCommun(noms)
  const groupes = noms.map(nom => ({
    nom: (prefixe && nom.length > prefixe.length ? nom.slice(prefixe.length) : nom).trim(),
    document_ids: parNom.get(nom)!,
  }))
  return { groupes, ecartes }
}
