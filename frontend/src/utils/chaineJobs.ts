/**
 * Suivi d'une CHAÎNE de jobs — le traitement d'un document est découpé en trois jobs (contenu,
 * enrichissement, embeddings) : chacun met le suivant en file en fin de succès et le dit dans son
 * résultat (`job_suivant`). Un seul `suivreJob` s'arrêterait au premier : l'interface annoncerait
 * « Fiche IA régénérée » alors que l'enrichissement n'a même pas démarré.
 */
import type { JobInfo } from '../api'

/** Garde-fou : la chaîne réelle compte trois maillons ; au-delà, on arrête plutôt que de boucler. */
const MAX_MAILLONS = 6

export interface ChaineSuivie {
  /** Le dernier job suivi : celui qui termine la chaîne, ou celui qui l'a interrompue. */
  final: JobInfo
  /** Tous les jobs suivis, dans l'ordre. */
  jobs: JobInfo[]
}

/** Le job a-t-il mis une suite en file ? (id non vide dans `resultat.job_suivant`) */
export function jobSuivant(job: JobInfo): string | null {
  const id = (job.resultat as { job_suivant?: unknown } | null)?.job_suivant
  return typeof id === 'string' && id.length > 0 ? id : null
}

/**
 * Suit `jobId` puis, tant que le job terminé avec succès annonce un `job_suivant`, ce job-là, jusqu'au
 * dernier. Un maillon en échec ou annulé arrête la chaîne (rien après lui). `suivre` est injecté
 * (`suivreJob` en production) : la logique se teste sans réseau.
 */
export async function suivreChaine(
  jobId: string,
  suivre: (id: string) => Promise<JobInfo>,
  options: {
    /** Appelé dès qu'un maillon est terminé, AVANT d'attendre le suivant (annonce sans attendre la fin). */
    onJob?: (job: JobInfo, jobs: JobInfo[]) => void | Promise<void>
  } = {},
): Promise<ChaineSuivie> {
  const jobs: JobInfo[] = []
  let courant: string | null = jobId
  while (courant && jobs.length < MAX_MAILLONS) {
    // Si `suivre` lève (écran quitté), l'exception remonte et plus aucun maillon n'est interrogé.
    const job = await suivre(courant)
    jobs.push(job)
    await options.onJob?.(job, jobs)
    courant = job.statut === 'completed' ? jobSuivant(job) : null
  }
  return { final: jobs[jobs.length - 1], jobs }
}

/** Dernier `statut` de document annoncé par un maillon de la chaîne (le plus récent gagne). */
export function statutDocument(jobs: JobInfo[]): string | undefined {
  for (let i = jobs.length - 1; i >= 0; i--) {
    const statut = (jobs[i].resultat as { statut?: unknown } | null)?.statut
    if (typeof statut === 'string') return statut
  }
  return undefined
}

/** Un maillon a-t-il signalé peu de contenu exploitable ? (`ok: false`, ou `sans_texte` : photo, vidéo muette) */
export function chaineSansContenu(jobs: JobInfo[]): boolean {
  return jobs.some(j => {
    const r = j.resultat as { ok?: unknown; sans_texte?: unknown } | null
    return r?.ok === false || r?.sans_texte === true
  })
}

/** Le maillon est-il l'enrichissement (ancien ou nouveau nom) terminé avec succès ? */
export function enrichissementTermine(job: JobInfo): boolean {
  return job.statut === 'completed' && (job.type === 'ia_enrich' || job.type === 'enrich')
}
