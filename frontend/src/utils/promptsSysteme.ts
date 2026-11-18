/**
 * Fonctions PURES de l'écran Paramètres › Prompts (plan prompts, étapes A4-A5) :
 * libellés, regroupement par usage, différence ligne à ligne entre deux textes.
 */

/** Libellés des familles d'usage IA (liste convenue avec l'AIGUILLEUR le 13/11/2026). */
const LIBELLES_USAGE: Record<string, string> = {
  chat: 'Chat & conversation',
  enrichissement: 'Enrichissement (indexation)',
  vision: 'Vision (images)',
  embeddings: 'Embeddings',
  rapport: 'Rapports',
  resume: 'Résumés',
  analyse: 'Analyses (comparatif, grille, fiches…)',
}
const ORDRE_USAGE = ['enrichissement', 'vision', 'chat', 'rapport', 'resume', 'analyse', 'embeddings']

export function libelleUsage(usage: string): string {
  return LIBELLES_USAGE[usage] ?? usage
}

/** « origine » (texte du code) ou « vN ». `origine` = la version active rend le texte du code. */
export function libelleVersion(version: number, origine: boolean): string {
  return version <= 0 || origine ? 'origine' : `v${version}`
}

/** Regroupe des prompts par usage, dans un ordre stable (usages connus d'abord), clés triées. */
export function regrouperParUsage<T extends { usage: string; cle: string }>(liste: T[]): { usage: string; libelle: string; prompts: T[] }[] {
  const groupes = new Map<string, T[]>()
  for (const p of liste) {
    const g = groupes.get(p.usage)
    if (g) g.push(p)
    else groupes.set(p.usage, [p])
  }
  const rang = (u: string) => { const i = ORDRE_USAGE.indexOf(u); return i < 0 ? ORDRE_USAGE.length : i }
  return [...groupes.entries()]
    .sort(([a], [b]) => rang(a) - rang(b) || a.localeCompare(b))
    .map(([usage, prompts]) => ({
      usage, libelle: libelleUsage(usage), prompts: [...prompts].sort((a, b) => a.cle.localeCompare(b.cle)),
    }))
}

export type LigneDiff = { type: 'egal' | 'ajout' | 'retrait'; texte: string }

/**
 * Différence ligne à ligne de `avant` vers `apres` (plus longue sous-suite commune).
 * Les retraits d'un bloc modifié précèdent ses ajouts. Textes de prompts : quelques centaines de
 * lignes au plus, la table n×m reste petite.
 */
export function diffLignes(avant: string, apres: string): LigneDiff[] {
  const a = avant.split('\n')
  const b = apres.split('\n')
  const n = a.length
  const m = b.length
  // lcs[i][j] = longueur de la plus longue sous-suite commune de a[i..] et b[j..]
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const sortie: LigneDiff[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) { sortie.push({ type: 'egal', texte: a[i] }); i++; j++ }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) { sortie.push({ type: 'retrait', texte: a[i] }); i++ }
    else { sortie.push({ type: 'ajout', texte: b[j] }); j++ }
  }
  while (i < n) sortie.push({ type: 'retrait', texte: a[i++] })
  while (j < m) sortie.push({ type: 'ajout', texte: b[j++] })
  return sortie
}

/** Nombre de lignes ajoutées / retirées. */
export function resumeDiff(diff: LigneDiff[]): { ajouts: number; retraits: number } {
  return {
    ajouts: diff.filter(l => l.type === 'ajout').length,
    retraits: diff.filter(l => l.type === 'retrait').length,
  }
}

/**
 * Noms des variables `{nom}` présentes dans un gabarit (accolades doublées ignorées). Sert
 * seulement à PRÉVENIR à l'écran ; le contrôle qui fait foi est celui du serveur (422).
 */
export function variablesDuTexte(texte: string): string[] {
  const vus: string[] = []
  const sansDoubles = texte.replace(/\{\{|\}\}/g, '')
  for (const m of sansDoubles.matchAll(/\{([^{}:!]*)(?:[!:][^{}]*)?\}/g)) {
    if (!vus.includes(m[1])) vus.push(m[1])
  }
  return vus
}

/** Variables déclarées absentes du texte, et variables du texte non déclarées. */
export function ecartVariables(texte: string, declarees: string[]): { manquantes: string[]; inconnues: string[] } {
  if (declarees.length === 0) return { manquantes: [], inconnues: [] }   // texte littéral : accolades libres
  const presentes = variablesDuTexte(texte)
  return {
    manquantes: declarees.filter(v => !presentes.includes(v)),
    inconnues: presentes.filter(v => !declarees.includes(v)),
  }
}
