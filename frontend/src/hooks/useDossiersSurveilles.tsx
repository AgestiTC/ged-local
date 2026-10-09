/**
 * Dossiers SURVEILLÉS (synchro automatique active) — une seule source de vérité pour tous les
 * explorateurs de Matothèque, et un seul repère visuel (`RepereSurveille`).
 *
 * Chaque arbre affichait ses dossiers sans dire lesquels Matothèque regarde tout seul : on
 * réglait la surveillance dans Paramètres, puis plus rien ne la rappelait ailleurs. La liste
 * est chargée une fois et partagée ; `rafraichirDossiersSurveilles()` la recharge après un
 * changement de réglage, et tous les arbres montés se mettent à jour.
 */
import { useEffect, useState } from 'react'
import { Eye } from 'lucide-react'
import { sourcesApi } from '../api'

type Surveille = { chemin: string; minutes: number; source: string }

let cache: Surveille[] | null = null
let enCours: Promise<void> | null = null
const abonnes = new Set<(liste: Surveille[]) => void>()

export function rafraichirDossiersSurveilles(): Promise<void> {
  enCours = sourcesApi.dossiersSurveilles()
    .then(liste => { cache = liste; abonnes.forEach(a => a(liste)) })
    .catch(() => { /* repère facultatif : un échec ne doit pas casser un arbre */ })
    .finally(() => { enCours = null })
  return enCours
}

/** « 1 h », « 6 h », « 24 h », « 30 min »… */
export function libelleFrequence(minutes: number): string {
  if (minutes % 1440 === 0) return minutes === 1440 ? '24 h' : `${minutes / 1440} j`
  if (minutes % 60 === 0) return `${minutes / 60} h`
  return `${minutes} min`
}

/** « toutes les heures », « toutes les 6 h »… (évite « toutes les 1 h »). */
export const phraseFrequence = (minutes: number) =>
  minutes === 60 ? 'toutes les heures' : `toutes les ${libelleFrequence(minutes)}`

/**
 * `surveillance(chemin)` : le dossier surveillé qui couvre ce chemin — lui-même (`direct`) ou
 * l'un de ses parents — ou `null`. Un dossier parent d'un dossier surveillé n'est PAS marqué :
 * « NAS-MATO » ne devient pas « surveillé » parce qu'un de ses 18 dossiers l'est.
 */
export function useDossiersSurveilles() {
  const [liste, setListe] = useState<Surveille[]>(cache ?? [])

  useEffect(() => {
    abonnes.add(setListe)
    if (cache) setListe(cache)
    else if (!enCours) void rafraichirDossiersSurveilles()
    return () => { abonnes.delete(setListe) }
  }, [])

  const surveillance = (chemin: string): (Surveille & { direct: boolean }) | null => {
    for (const s of liste) {
      if (chemin === s.chemin) return { ...s, direct: true }
      if (chemin.startsWith(s.chemin + '/')) return { ...s, direct: false }
    }
    return null
  }
  return { surveillance, nombre: liste.length }
}

/** Le repère commun : un œil vert, plein sur le dossier surveillé, discret sur son contenu. */
export function RepereSurveille({ minutes, direct = true, taille = 12 }: { minutes: number; direct?: boolean; taille?: number }) {
  return (
    <span className="shrink-0 inline-flex" role="img"
      aria-label={direct ? 'Dossier surveillé' : 'Dans un dossier surveillé'}
      title={direct
        ? `Dossier surveillé — synchronisé automatiquement ${phraseFrequence(minutes)}`
        : `Dans un dossier surveillé (${phraseFrequence(minutes)})`}>
      <Eye size={taille} className={direct ? 'text-emerald-600' : 'text-emerald-300'} />
    </span>
  )
}

/** Couleur de l'icône « dossier » : verte s'il est surveillé, ambre sinon. */
export const couleurDossier = (surveille: boolean) => (surveille ? 'text-emerald-600' : 'text-amber-500')
