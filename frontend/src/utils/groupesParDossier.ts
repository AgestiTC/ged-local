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

/** Un sous-dossier du dossier coché, avec les documents (utilisables) qu'il contient. */
export interface SousDossier {
  nom: string
  document_ids: string[]
}

/**
 * Candidats créés en cochant UN dossier dans « Quels documents ? » (04/11/2026) : un candidat par
 * sous-dossier, nommé d'après lui (préfixe commun « OFFRE_ » retiré, comme ci-dessus).
 * Un nom déjà pris par un candidat existant ne crée pas de doublon : ses documents manquants
 * sont ajoutés à ce candidat (`completes`). Un sous-dossier sans document utilisable est écarté.
 */
export function candidatsDepuisSousDossiers(
  sousDossiers: SousDossier[],
  existants: Array<{ id: string; nom: string; document_ids: string[] }>,
): { nouveaux: GroupeDossier[]; completes: Map<string, string[]>; vides: string[] } {
  const utiles = sousDossiers.filter(s => s.document_ids.length > 0)
  const vides = sousDossiers.filter(s => s.document_ids.length === 0).map(s => s.nom)
  const prefixe = prefixeCommun(utiles.map(s => s.nom))
  const nouveaux: GroupeDossier[] = []
  const completes = new Map<string, string[]>()
  for (const s of utiles) {
    const nom = (prefixe && s.nom.length > prefixe.length ? s.nom.slice(prefixe.length) : s.nom).trim()
    const deja = existants.find(g => g.nom.trim().toLowerCase() === nom.toLowerCase())
    if (deja) {
      const manquants = s.document_ids.filter(id => !deja.document_ids.includes(id))
      if (manquants.length) completes.set(deja.id, manquants)
    } else {
      nouveaux.push({ nom, document_ids: s.document_ids })
    }
  }
  return { nouveaux, completes, vides }
}

/** CCTP ou règlement de consultation, d'après le NOM du fichier. */
export const estDocumentMarche = (nom: string): boolean =>
  /cctp|r[eè]glement[\s_-]*(de[\s_-]*)?(la[\s_-]*)?consultation|(^|[^a-z0-9])rc([^a-z0-9]|$)/i.test(nom)

/** Sous-dossier qui porte les pièces du marché (DCE…), et non une offre. */
export const estDossierMarche = (nom: string): boolean =>
  /^(dce|march[eé]s?|cctp|rc|consultation|dossier[\s_-]*de[\s_-]*consultation|pi[eè]ces?[\s_-]*(du[\s_-]*)?march[eé])$/i
    .test(nom.trim())

/**
 * Dossier de consultation coché (04/11/2026) : ce qui est au marché, ce qui est aux candidats.
 * - fichier posé à la racine et nommé CCTP / règlement → documents du marché ; autre fichier → ignoré ;
 * - sous-dossier « DCE », « Marché »… → tous ses documents vont au marché ;
 * - tout autre sous-dossier → un candidat.
 */
export function repartirDossierConsultation(
  sousDossiers: SousDossier[],
  fichiersRacine: Array<{ id: string; nom: string; exploitable?: boolean }>,
): { candidats: SousDossier[]; marche: string[]; ignores: number } {
  const utilisables = fichiersRacine.filter(f => f.exploitable !== false)
  const marche = [
    ...utilisables.filter(f => estDocumentMarche(f.nom)).map(f => f.id),
    ...sousDossiers.filter(s => estDossierMarche(s.nom)).flatMap(s => s.document_ids),
  ]
  return {
    candidats: sousDossiers.filter(s => !estDossierMarche(s.nom)),
    marche: [...new Set(marche)],
    ignores: fichiersRacine.length - utilisables.filter(f => estDocumentMarche(f.nom)).length,
  }
}
