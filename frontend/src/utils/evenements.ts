/**
 * Petits signaux entre écrans qui ne se connaissent pas.
 *
 * La barre latérale affiche l'arborescence des dossiers, mais ce sont d'AUTRES pages qui la
 * modifient (création depuis la liste, sous-dossier depuis le détail, installation d'un
 * pré-rempli). Elles n'ont aucune raison de se connaître, et remonter un état partagé
 * jusqu'au layout pour trois mutations serait disproportionné.
 *
 * Un événement du navigateur suffit : celui qui modifie le crie, celui qui affiche écoute.
 * Pas de dépendance, pas de store, et rien à défaire si l'un des deux disparaît.
 */

/** Les dossiers (ou leurs sous-dossiers) ont changé : ce qui les affiche doit relire. */
export const DOSSIERS_MAJ = 'mtq:dossiers-maj'

/** À appeler APRÈS une création, une suppression ou l'installation d'un dossier pré-rempli. */
export function signalerDossiersMaj(): void {
  window.dispatchEvent(new Event(DOSSIERS_MAJ))
}
