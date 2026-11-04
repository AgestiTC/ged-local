/**
 * Variables des instructions du Tableau comparatif (04/11/2026).
 *
 * Une consigne réutilisée d'un appel d'offres à l'autre ne doit pas être réécrite à chaque fois :
 *   « … de l'appel d'offres [DOSSIER PARENT]. »                       → « … de l'appel d'offres MA26050. »
 *   « … selon le règlement de consultation [un fichier nommé *RC_MOE_COLLEBASSE*]. »
 *                                    → « … selon le règlement de consultation. » + ce fichier
 *                                      ajouté aux documents du marché.
 * Le crochet qui désigne un fichier disparaît du texte envoyé à l'IA : elle reçoit le document
 * lui-même, pas son nom de fichier.
 */

const DOSSIER_PARENT = /\[\s*dossier[\s_-]*parent\s*\]/gi
const FICHIER = /\s*\[[^\]]*?\*([^*\]]+)\*[^\]]*\]/g

export interface ConsigneResolue {
  texte: string
  /** Motifs de noms de fichiers désignés dans la consigne (sans les étoiles). */
  motifs: string[]
  /** `[DOSSIER PARENT]` présent mais aucun dossier connu pour le remplacer. */
  dossierManquant: boolean
}

export function contientVariables(texte: string): boolean {
  return new RegExp(DOSSIER_PARENT.source, 'i').test(texte) || new RegExp(FICHIER.source).test(texte)
}

export function resoudreConsigne(texte: string, dossier: string | null): ConsigneResolue {
  const motifs: string[] = []
  let dossierManquant = false
  const sansFichiers = texte.replace(FICHIER, (_m, motif: string) => { motifs.push(motif.trim()); return '' })
  const resolu = sansFichiers.replace(DOSSIER_PARENT, m => {
    if (dossier) return dossier
    dossierManquant = true
    return m
  })
  return { texte: resolu.replace(/[ \t]+([.,;:])/g, '$1'), motifs, dossierManquant }
}

// « RC_MOE_COLLEBASSE » retrouve « RC MOE Collebasse.pdf » comme « rc-moe_collebasse v2.docx ».
const normaliser = (s: string) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/[\s_.-]+/g, ' ').trim()

export function correspondAuMotif(nomFichier: string, motif: string): boolean {
  const m = normaliser(motif)
  return !!m && normaliser(nomFichier).includes(m)
}

/** Rôle d'une pièce du marché d'après son nom — affiché en étiquette. */
export function roleMarche(nom: string): 'CCTP' | 'RC' | null {
  if (/cctp/i.test(nom)) return 'CCTP'
  if (/r[eè]glement[\s_-]*(de[\s_-]*)?(la[\s_-]*)?consultation|(^|[^a-z0-9])rc([^a-z0-9]|$)/i.test(nom)) return 'RC'
  return null
}
