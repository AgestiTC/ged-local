/**
 * JobsIndicator — widget « Tâches en cours » (Header)
 * ===================================================
 * Poll les jobs durables (`/api/jobs`) toutes les 2,5 s, affiche un badge + une liste
 * déroulante (progression, annulation) et émet un toast à la complétion — même si on est
 * sur une autre page. Comme les jobs vivent en base, revenir/rouvrir l'appli les retrouve.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, ListChecks, X, CheckCircle2, AlertCircle, Ban } from 'lucide-react'
import { clsx } from 'clsx'
import { jobsApi, type JobInfo } from '../../api'
import { useJobsStore, jobActif } from '../../stores/jobsStore'
import { useToast } from '../common/Toast'

const LABEL: Record<string, string> = {
  enrich: 'Analyse IA',
  analyze: 'Analyse du contenu',
  extraction: 'Analyse complète',
  presentation: 'Présentation',
  comparatif: 'Tableau comparatif',
  rapport: 'Rapport',
  fill_template: 'Remplissage modèle',
  indexation: 'Indexation',
  sync_source: 'Synchronisation',
  reorg_apply: 'Rangement NAS',
  reorg_undo: 'Annulation rangement',
  demo: 'Démo',
}
const lab = (t: string) => LABEL[t] ?? t

// Dossier visé par une indexation / synchro : sans lui, 18 lignes « Indexation » identiques ne
// disent pas où en est Matothèque. `partage` lève l'ambiguïté des homonymes (deux « Non classé »).
function cible(j: JobInfo): { dossier: string; partage: string | null } | null {
  if (j.type !== 'indexation' && j.type !== 'sync_source') return null
  const p = j.parametres ?? {}
  const partage = typeof p.partage === 'string' && p.partage ? p.partage : null
  const chemin = typeof p.chemin === 'string' ? p.chemin.replace(/^\/+|\/+$/g, '') : ''
  if (chemin) return { dossier: chemin, partage }
  return partage ? { dossier: partage, partage: null } : null
}
const titre = (j: JobInfo) => { const c = cible(j); return c ? `${lab(j.type)} — ${c.dossier}` : lab(j.type) }
const cheminComplet = (j: JobInfo) => { const c = cible(j); return c ? [c.partage, c.dossier].filter(Boolean).join('/') : undefined }

// Temps restant d'une tâche EN COURS, extrapolé de son rythme depuis le démarrage. `null` tant
// qu'on ne peut rien affirmer (énumération à 0 %, démarrage trop récent) : mieux vaut ne rien
// afficher qu'un chiffre inventé. Une tâche en file n'a pas d'estimation — sa taille est inconnue.
function resteSecondes(j: JobInfo): number | null {
  if (j.statut !== 'running' || !j.started_at || j.progress <= 0 || j.progress >= 100) return null
  const ecoule = (Date.now() - new Date(j.started_at).getTime()) / 1000
  if (!(ecoule >= 20)) return null
  // `fait/total` (indexation) est plus fin que le pourcentage entier.
  const fait = Number(j.resultat?.fait), total = Number(j.resultat?.total)
  const part = fait > 0 && total > 0 ? Math.min(fait / total, 1) : j.progress / 100
  return part > 0 && part < 1 ? ecoule * (1 - part) / part : null
}

function duree(s: number): string {
  if (s < 60) return `${Math.max(1, Math.round(s))} s`
  const min = Math.floor(s / 60)
  if (min < 10) return `${min} min ${String(Math.round(s % 60)).padStart(2, '0')} s`
  if (min < 60) return `${min} min`
  return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, '0')} min`
}

function Titre({ job }: { job: JobInfo }) {
  const c = cible(job)
  return (
    <span className="flex-1 truncate" title={cheminComplet(job)}>
      {lab(job.type)}
      {c && <> — {c.dossier}{c.partage && <span className="font-normal text-gray-400"> · {c.partage}</span>}</>}
    </span>
  )
}

export default function JobsIndicator() {
  const { jobs, setJobs } = useJobsStore()
  const [open, setOpen] = useState(false)
  // Compteurs RÉELS (COUNT en base) : la liste ci-dessous est plafonnée à 20 → sur un gros lot
  // elle sur-comptait (« 22 » = fenêtre, pas la réalité). Le badge s'appuie sur ces vrais totaux.
  const [stats, setStats] = useState<{ running: number; pending: number }>({ running: 0, pending: 0 })
  const toast = useToast()
  const prev = useRef<Map<string, string>>(new Map())
  const monte = useRef(true)
  // Remis à vrai à chaque montage : en développement, React monte / démonte / remonte, et sans
  // cela le widget se croyait démonté pour toujours (liste vide alors que l'API répondait).
  useEffect(() => { monte.current = true; return () => { monte.current = false } }, [])

  // Extrait en useCallback pour pouvoir forcer un rafraîchissement à l'ouverture du menu
  // (pas seulement au prochain tick du polling) → état toujours frais quand on regarde.
  const poll = useCallback(async () => {
    try {
      // Les 20 plus récents (dropdown/toasts) + les jobs qui TOURNENT (souvent plus anciens,
      // hors des 20 sur un gros lot) → la mini-barre suit un job réel au lieu de rester à 0 %.
      const [recents, running, s] = await Promise.all([
        jobsApi.list({ limit: 20 }).then(r => r.jobs),
        jobsApi.list({ statut: 'running', limit: 8 }).then(r => r.jobs).catch(() => [] as JobInfo[]),
        jobsApi.stats().catch(() => ({ running: 0, pending: 0, actifs: 0 })),
      ])
      if (!monte.current) return
      setStats({ running: s.running, pending: s.pending })
      const byId = new Map<string, JobInfo>()
      for (const j of [...running, ...recents]) byId.set(j.id, j)
      const liste = [...byId.values()]
      // Toast de complétion : un job actif au tick précédent qui ne l'est plus.
      for (const j of liste) {
        const avant = prev.current.get(j.id)
        if (avant && jobActif(avant) && !jobActif(j.statut)) {
          if (j.statut === 'completed') toast.success(`${titre(j)} : terminé`)
          else if (j.statut === 'failed') toast.error(`${titre(j)} : échec`)
        }
      }
      prev.current = new Map(liste.map(j => [j.id, j.statut]))
      setJobs(liste)
    } catch { /* silencieux */ }
  }, [setJobs, toast])

  useEffect(() => {
    poll()
    const t = setInterval(poll, 2500)
    return () => clearInterval(t)
  }, [poll])

  const actifs = jobs.filter(j => jobActif(j.statut))
  const recents = jobs.filter(j => !jobActif(j.statut)).slice(0, 5)
  // Vrais totaux (COUNT base) pour le badge : « N en cours » (+ « M en file » si file d'attente).
  const totalActifs = stats.running + stats.pending
  // Tâche mise en avant dans le header : en priorité une qui tourne vraiment (sinon barre
  // figée à 0 % sur un gros lot où seuls les jobs anciens — hors fenêtre — sont en cours).
  const enTete = actifs.find(j => j.statut === 'running') ?? actifs[0]
  // Les tâches en cours avancent EN PARALLÈLE : le temps restant est celui de la plus longue.
  const restes = actifs.map(resteSecondes).filter((s): s is number => s !== null)
  const resteMax = restes.length ? Math.max(...restes) : null

  const annuler = async (id: string) => { try { await jobsApi.cancel(id) } catch { /* ignore */ } }

  return (
    <div className="relative">
      <button
        type="button"
        // À l'ouverture, on force un refresh immédiat (sans attendre le prochain tick de 2,5 s).
        onClick={() => { if (!open) poll(); setOpen(o => !o) }}
        className={clsx('flex items-center gap-1.5 px-2 py-1 rounded-md text-xs transition-colors',
          totalActifs ? 'text-blue-600 bg-blue-50' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100')}
        title={totalActifs ? `${stats.running} en cours · ${stats.pending} en file d'attente` : 'Aucune tâche active'}
      >
        {totalActifs ? <Loader2 size={14} className="animate-spin" /> : <ListChecks size={14} />}
        <span>
          Tâches{stats.running ? ` · ${stats.running.toLocaleString('fr-FR')} en cours` : ''}
          {stats.pending ? <span className="text-blue-400"> · {stats.pending.toLocaleString('fr-FR')} en file</span> : ''}
        </span>
        {/* Mini-barre de progression : visible sans ouvrir le menu */}
        {enTete && (
          <span className="flex items-center gap-1" title={`${titre(enTete)} — ${enTete.progress}%`}>
            <span className="w-12 h-1 bg-blue-100 rounded-full overflow-hidden">
              <span className="block h-full bg-blue-500 transition-all" style={{ width: `${enTete.progress}%` }} />
            </span>
            <span className="tabular-nums text-[10px] text-blue-600">{enTete.progress}%</span>
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 w-80 bg-white border border-gray-200 rounded-lg shadow-lg z-50 max-h-96 overflow-y-auto">
            <div className="px-3 py-2 border-b border-gray-100 flex items-baseline justify-between gap-2">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Tâches</span>
              {resteMax !== null && (
                <span className="text-[10px] text-gray-400 tabular-nums"
                  title={"Temps restant estimé pour les tâches en cours, d'après leur rythme depuis le démarrage."
                    + (stats.pending ? ` Les ${stats.pending} tâches en file ne sont pas comptées : leur taille n'est connue qu'une fois démarrées.` : '')}>
                  ≈ {duree(resteMax)} restant{stats.pending ? ' · hors file' : ''}
                </span>
              )}
            </div>

            {actifs.length === 0 && recents.length === 0 && (
              <p className="px-3 py-5 text-xs text-gray-400 text-center">Aucune tâche récente</p>
            )}

            {actifs.map(j => (
              <div key={j.id} className="px-3 py-2 border-b border-gray-50">
                <div className="flex items-center gap-2 text-xs">
                  <Loader2 size={12} className="animate-spin text-blue-500 shrink-0" />
                  <span className="font-medium text-gray-700 flex-1 min-w-0 flex"><Titre job={j} /></span>
                  {resteSecondes(j) !== null && (
                    <span className="text-[10px] text-gray-400 tabular-nums shrink-0" title="Temps restant estimé">
                      ≈ {duree(resteSecondes(j) as number)}
                    </span>
                  )}
                  <span className="text-gray-400 shrink-0">{j.progress}%</span>
                  <button type="button" onClick={() => annuler(j.id)} title="Annuler"
                    className="text-gray-300 hover:text-red-500"><X size={12} /></button>
                </div>
                <div className="h-1 bg-gray-100 rounded-full overflow-hidden mt-1">
                  <div className="h-full bg-blue-500 transition-all" style={{ width: `${j.progress}%` }} />
                </div>
                {j.progress_message && <p className="text-[10px] text-gray-400 mt-0.5 truncate">{j.progress_message}</p>}
              </div>
            ))}

            {recents.map(j => (
              <div key={j.id} className="px-3 py-1.5 flex items-center gap-2 text-xs text-gray-400">
                {j.statut === 'completed'
                  ? <CheckCircle2 size={12} className="text-green-400 shrink-0" />
                  : j.statut === 'failed'
                  ? <AlertCircle size={12} className="text-red-400 shrink-0" />
                  : <Ban size={12} className="shrink-0" />}
                <Titre job={j} />
                <span>{j.statut === 'completed' ? 'OK' : j.statut === 'failed' ? 'échec' : 'annulé'}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
