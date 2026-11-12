import { describe, expect, it, vi } from 'vitest'
import type { JobInfo } from '../../api'
import { chaineSansContenu, enrichissementTermine, jobSuivant, statutDocument, suivreChaine } from '../../utils/chaineJobs'

// Jobs 100 % fictifs.
function job(id: string, statut: JobInfo['statut'], resultat: Record<string, unknown> | null = null, type = 'ia_contenu'): JobInfo {
  return {
    id, type, statut, progress: 100, progress_message: null, document_id: null,
    parametres: null, resultat, erreur: null, created_at: null, started_at: null, completed_at: null,
  }
}

function suiveur(jobs: Record<string, JobInfo>) {
  return vi.fn(async (id: string) => jobs[id])
}

describe('jobSuivant', () => {
  it('lit l’id annoncé, ignore le vide et l’absent', () => {
    expect(jobSuivant(job('a', 'completed', { job_suivant: 'b' }))).toBe('b')
    expect(jobSuivant(job('a', 'completed', { job_suivant: null }))).toBeNull()
    expect(jobSuivant(job('a', 'completed', { job_suivant: '' }))).toBeNull()
    expect(jobSuivant(job('a', 'completed', null))).toBeNull()
  })
})

describe('suivreChaine', () => {
  it('suit contenu → enrichissement → embeddings jusqu’au dernier', async () => {
    const suivre = suiveur({
      a: job('a', 'completed', { job_suivant: 'b', statut: 'extracted' }),
      b: job('b', 'completed', { job_suivant: 'c', statut: 'enriched' }),
      c: job('c', 'completed', { nb_chunks: 3 }),
    })
    const { final, jobs } = await suivreChaine('a', suivre)
    expect(final.id).toBe('c')
    expect(jobs.map(j => j.id)).toEqual(['a', 'b', 'c'])
    expect(suivre).toHaveBeenCalledTimes(3)
  })

  it('un job sans suite termine la chaîne dès le premier (photo sans texte)', async () => {
    const suivre = suiveur({ a: job('a', 'completed', { sans_texte: true, job_suivant: null }) })
    const { final, jobs } = await suivreChaine('a', suivre)
    expect(final.id).toBe('a')
    expect(jobs).toHaveLength(1)
  })

  it('un maillon en échec arrête la chaîne et c’est lui qui est rendu', async () => {
    const suivre = suiveur({
      a: job('a', 'completed', { job_suivant: 'b' }),
      b: { ...job('b', 'failed'), erreur: 'aucune catégorie exploitable' },
      c: job('c', 'completed'),
    })
    const { final } = await suivreChaine('a', suivre)
    expect(final.id).toBe('b')
    expect(final.statut).toBe('failed')
    expect(suivre).not.toHaveBeenCalledWith('c')
  })

  it('un job annulé ne déclenche pas le suivi de sa suite', async () => {
    const suivre = suiveur({ a: job('a', 'cancelled', { job_suivant: 'b' }) })
    const { final } = await suivreChaine('a', suivre)
    expect(final.statut).toBe('cancelled')
    expect(suivre).toHaveBeenCalledTimes(1)
  })

  it('ne boucle pas si un job se désigne lui-même', async () => {
    const suivre = suiveur({ a: job('a', 'completed', { job_suivant: 'a' }) })
    const { jobs } = await suivreChaine('a', suivre)
    expect(jobs.length).toBeLessThanOrEqual(6)
  })
})

describe('lecture du résultat de la chaîne', () => {
  it('le statut du document est le plus récent annoncé', () => {
    const jobs = [
      job('a', 'completed', { statut: 'extracted' }),
      job('b', 'completed', { statut: 'enriched' }),
      job('c', 'completed', { nb_chunks: 2 }),
    ]
    expect(statutDocument(jobs)).toBe('enriched')
    expect(statutDocument([job('c', 'completed', {})])).toBeUndefined()
  })

  it('signale un maillon sans contenu exploitable', () => {
    expect(chaineSansContenu([job('a', 'completed', { ok: true }), job('b', 'completed', { ok: false })])).toBe(true)
    expect(chaineSansContenu([job('a', 'completed', { ok: true, sans_texte: true })])).toBe(true)
    expect(chaineSansContenu([job('a', 'completed', { ok: true, sans_texte: false })])).toBe(false)
  })
})

describe('suivi maillon par maillon (M3)', () => {
  it('prévient à chaque maillon terminé, dans l’ordre, avant de passer au suivant', async () => {
    const suivre = suiveur({
      a: job('a', 'completed', { job_suivant: 'b' }, 'ia_contenu'),
      b: job('b', 'completed', { job_suivant: 'c' }, 'ia_enrich'),
      c: job('c', 'failed', null, 'ia_embed'),
    })
    const vus: string[] = []
    const { final } = await suivreChaine('a', suivre, { onJob: j => { vus.push(`${j.id}:${suivre.mock.calls.length}`) } })
    // « a » est annoncé après 1 lecture, « b » après 2 : l’annonce ne attend pas la fin de la chaîne.
    expect(vus).toEqual(['a:1', 'b:2', 'c:3'])
    expect(final.type).toBe('ia_embed')
  })

  it('s’arrête net si le suivi lève (écran quitté) : pas de maillon suivant interrogé', async () => {
    let appels = 0
    const suivre = vi.fn(async (id: string) => {
      appels += 1
      if (appels > 1) throw new Error('démonté')
      return job(id, 'completed', { job_suivant: 'b' })
    })
    await expect(suivreChaine('a', suivre)).rejects.toThrow('démonté')
    expect(appels).toBe(2)
  })

  it('reconnaît la fin de l’enrichissement (ancien et nouveau nom), pas celle d’un autre maillon', () => {
    expect(enrichissementTermine(job('b', 'completed', {}, 'ia_enrich'))).toBe(true)
    expect(enrichissementTermine(job('b', 'completed', {}, 'enrich'))).toBe(true)
    expect(enrichissementTermine(job('b', 'failed', null, 'ia_enrich'))).toBe(false)
    expect(enrichissementTermine(job('c', 'completed', {}, 'ia_embed'))).toBe(false)
  })
})
