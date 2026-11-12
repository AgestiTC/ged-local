/**
 * OptionsModeles — enfants d'un <select> : un <optgroup> par origine (GECO, MATO…).
 * L'optgroup est rendu même quand il est seul : l'utilisateur veut voir « MATO ».
 * L'état d'une option se déduit de `selectionnable`, JAMAIS de l'origine.
 */
import { grouperModeles, type ModeleListe } from '../../utils/modeles'
import { sansEmbeddings } from '../../utils/iaDestination'

interface Props<T extends ModeleListe> {
  modeles: T[]
  /** Modèles d'une IA externe (GECO) : forme minimale, sans taille ni métadonnées Ollama. */
  externes?: ModeleListe[]
  /**
   * Libellé d'une option des modèles INSTALLÉS (défaut : le nom) : nom court, taille, 😈…
   * Les modèles externes gardent leur nom (ils n'ont pas ces métadonnées) ; la mention
   * « internet » est ajoutée ici dans les deux cas.
   */
  libelle?: (m: T) => string
  /** Garde seulement les modèles pour lesquels il rend vrai (ex. masquer les embeddings). */
  filtre?: (m: ModeleListe) => boolean
}

export function OptionsModeles<T extends ModeleListe>({ modeles, externes, libelle, filtre }: Props<T>) {
  const garder = <U extends ModeleListe>(liste?: U[]) => (filtre ? liste?.filter(filtre) : liste)
  const locaux = garder(modeles) ?? []
  const estLocal = new Set<ModeleListe>(locaux)   // identité d'objet : sépare installés / externes
  // Texte de base d'une option — sert AUSSI de clé de tri : on trie ce que l'utilisateur lit.
  const texte = (m: ModeleListe) => (libelle && estLocal.has(m) ? libelle(m as T) : m.name)
  // Un modèle GECO d'embeddings n'a rien à faire dans un sélecteur (chat, rapport…) : masqué partout.
  const groupes = grouperModeles<ModeleListe>(locaux, garder(sansEmbeddings(externes)), texte)
  return (
    <>
      {groupes.map(g => (
        <optgroup key={g.groupe} label={g.groupe}>
          {g.modeles.map(m => {
            const bloque = m.selectionnable === false
            const base = texte(m)
            // « réservé au mode IA GECO » ne vaut que pour une option d'origine GECO non sélectionnable.
            const mention = g.groupe === 'GECO' ? (bloque ? ' · internet — réservé au mode IA GECO' : ' · internet') : ''
            return (
              <option key={m.name} value={m.name} title={m.name + mention} disabled={bloque}>
                {base + mention}
              </option>
            )
          })}
        </optgroup>
      ))}
    </>
  )
}
