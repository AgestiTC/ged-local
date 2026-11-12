/**
 * Groupement des modèles par origine (MATO = Ollama de PC-GAME, GECO = IA externe).
 * Fonction pure : ne mute pas ses entrées. Le groupe est un classement d'AFFICHAGE, il ne
 * change ni le routage par usage ni le choix « Auto ». Voir docs/plan-liste-modeles.md.
 */

/** Forme minimale d'un modèle affichable (compatible `OllamaModel` et `ModeleExterne`). */
export interface ModeleListe {
  name: string
  origine?: string
  selectionnable?: boolean
  embedding?: boolean   // modèle GECO d'embeddings : jamais proposé (chat, modèle GECO utilisé)
}

export interface GroupeModeles<T extends ModeleListe = ModeleListe> {
  groupe: string
  modeles: T[]
}

const GROUPE_DEFAUT = 'MATO'                 // un modèle sans origine (ancien backend) est un modèle Ollama
const ORDRE_FIXE = ['GECO', 'MATO']

const comparerNoms = (a: string, b: string) => a.localeCompare(b, 'fr', { sensitivity: 'base' })

function rangGroupe(groupe: string): number {
  const i = ORDRE_FIXE.indexOf(groupe)
  return i === -1 ? ORDRE_FIXE.length : i
}

/**
 * `cle` : texte sur lequel trier (défaut : le nom). À fournir quand le libellé AFFICHÉ diffère du
 * nom — sinon « hf.co/org/Zebre » raccourci en « Zebre » se retrouve avant « llama3.1 », et la
 * liste paraît en désordre (constaté à la vérification du 12/11/2026).
 */
export function grouperModeles<T extends ModeleListe>(
  modeles: T[], externes?: T[], cle: (m: T) => string = m => m.name,
): GroupeModeles<T>[] {
  const parGroupe = new Map<string, T[]>()
  for (const m of [...modeles, ...(externes ?? [])]) {
    const groupe = m.origine || GROUPE_DEFAUT
    const liste = parGroupe.get(groupe)
    if (liste) liste.push(m)
    else parGroupe.set(groupe, [m])
  }
  return [...parGroupe.entries()]
    .sort(([a], [b]) => rangGroupe(a) - rangGroupe(b) || comparerNoms(a, b))
    .map(([groupe, liste]) => ({ groupe, modeles: [...liste].sort((a, b) => comparerNoms(cle(a), cle(b))) }))
}
