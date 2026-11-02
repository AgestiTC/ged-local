/**
 * FileIA — « pourquoi ma tâche attend, derrière quoi, jusqu'à quand », et quoi y faire.
 *
 * Plan docs/plan-file-ia-priorites.md, étape 5 (02/11/2026). Le comparatif affichait « d'autres tâches
 * IA passent avant » alors que rien ne tournait (pause IA oubliée), sans aucun moyen d'agir.
 * Ici : la vraie raison, la position, les tâches en cours / devant (type et avancement, JAMAIS leur
 * contenu), un démarrage estimé, et trois actions :
 *   - Continuer        → passe au prochain créneau GPU libre (ne coupe aucune tâche en cours) ;
 *   - Laisser en file  → garde sa place (le repère temporel reste affiché) ;
 *   - Annuler          → arrête la tâche (confirmation en ligne).
 * Rafraîchi toutes les 5 s tant que la tâche attend ; disparaît à son démarrage.
 */
import { useCallback, useEffect, useState } from 'react'
import { Clock, FastForward, Hourglass, Loader, PauseCircle, X } from 'lucide-react'
import { extractApiError, jobsApi, type FileIAEtat, type TacheFileIA } from '../../api'
import { useToast } from './Toast'

const RAFRAICHISSEMENT_MS = 5_000

function heure(iso: string): string {
  return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

function depuis(iso: string | null): string {
  if (!iso) return ''
  const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  return min < 1 ? "à l'instant" : min < 60 ? `depuis ${min} min` : `depuis ${Math.floor(min / 60)} h ${min % 60} min`
}

function Ligne({ t }: { t: TacheFileIA }) {
  return (
    <li className="flex items-center justify-between gap-2">
      <span className="truncate">
        {t.libelle}
        {t.creer && <span className="ml-1 text-[10px] text-blue-600">· Créer</span>}
        {t.prioritaire && <span className="ml-1 text-[10px] text-amber-700">· prioritaire</span>}
      </span>
      <span className="shrink-0 text-gray-400">
        {t.statut === 'running' ? `${t.avancement} % · ` : ''}{depuis(t.depuis)}
      </span>
    </li>
  )
}

export default function FileIA({ jobId }: { jobId: string }) {
  const toast = useToast()
  const [etat, setEtat] = useState<FileIAEtat | null>(null)
  const [laisse, setLaisse] = useState(false)
  const [confirmeAnnuler, setConfirmeAnnuler] = useState(false)
  const [action, setAction] = useState<'prioriser' | 'annuler' | null>(null)

  const lire = useCallback(() => {
    jobsApi.file(jobId).then(setEtat).catch(() => { /* silencieux : la progression reste affichée */ })
  }, [jobId])

  useEffect(() => {
    lire()
    const id = setInterval(lire, RAFRAICHISSEMENT_MS)
    return () => clearInterval(id)
  }, [lire])

  if (!etat || etat.statut !== 'pending') return null

  const prioriser = async () => {
    setAction('prioriser')
    try {
      await jobsApi.prioriser(jobId)
      toast.success('La tâche passe au prochain créneau libre — aucune tâche en cours n\'est coupée.')
      lire()
    } catch (e) { toast.error(extractApiError(e)) } finally { setAction(null) }
  }

  const annuler = async () => {
    setAction('annuler')
    try {
      await jobsApi.cancel(jobId)
      toast.success('Tâche annulée.')
      lire()
    } catch (e) { toast.error(extractApiError(e)) } finally { setAction(null); setConfirmeAnnuler(false) }
  }

  const Icone = etat.raison === 'pause_ia' ? PauseCircle : etat.raison === 'demarrage' ? Loader : Hourglass

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50/50 p-3 space-y-2 text-xs">
      <div className="flex items-start gap-2">
        <Icone size={15} className={etat.raison === 'demarrage' ? 'animate-spin text-blue-600 shrink-0 mt-0.5' : 'text-blue-600 shrink-0 mt-0.5'} />
        <div className="space-y-0.5">
          <p className="font-medium text-blue-900">{etat.message}</p>
          <p className="text-gray-600">
            {etat.position !== null && <>Position <strong>{etat.position}</strong>{etat.nb_devant > 0 && ` (${etat.nb_devant} devant)`}</>}
            {etat.estimation && (
              <> · <Clock size={11} className="inline -mt-0.5" /> démarrage estimé vers <strong>{heure(etat.estimation.debut)}</strong>
                {' '}({etat.estimation.plafonnee ? 'plus de 24 h' : `≈ ${etat.estimation.minutes} min`})</>
            )}
            {etat.prioritaire && <> · <strong className="text-amber-700">prioritaire</strong></>}
          </p>
        </div>
      </div>

      {(etat.en_cours.length > 0 || etat.devant.length > 0) && (
        <div className="grid gap-2 sm:grid-cols-2 text-gray-700">
          {etat.en_cours.length > 0 && (
            <div>
              <p className="font-semibold text-gray-500 mb-0.5">En cours ({etat.en_cours.length}/{etat.budget})</p>
              <ul className="space-y-0.5">{etat.en_cours.map((t, i) => <Ligne key={`c${i}`} t={t} />)}</ul>
            </div>
          )}
          {etat.devant.length > 0 && (
            <div>
              <p className="font-semibold text-gray-500 mb-0.5">Devant cette tâche ({etat.nb_devant})</p>
              <ul className="space-y-0.5">{etat.devant.map((t, i) => <Ligne key={`d${i}`} t={t} />)}</ul>
            </div>
          )}
        </div>
      )}

      {!laisse && (
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          {etat.peut_prioriser && (
            <button type="button" onClick={prioriser} disabled={action !== null}
              title="Part au prochain créneau libre, devant tout le reste. Ne coupe aucune tâche en cours."
              className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-60">
              {action === 'prioriser' ? <Loader size={12} className="animate-spin" /> : <FastForward size={12} />} Continuer
            </button>
          )}
          <button type="button" onClick={() => setLaisse(true)}
            title="Garde sa place dans la file ; le repère temporel reste affiché."
            className="px-2.5 py-1 rounded-md border border-gray-300 text-gray-700 hover:bg-white">
            Laisser en file
          </button>
          {confirmeAnnuler ? (
            <span className="flex items-center gap-1">
              <span className="text-red-700">Annuler cette tâche ?</span>
              <button type="button" onClick={annuler} disabled={action !== null}
                className="px-2 py-1 rounded-md bg-red-600 text-white hover:bg-red-700 disabled:opacity-60">Oui, annuler</button>
              <button type="button" onClick={() => setConfirmeAnnuler(false)}
                className="px-2 py-1 rounded-md border border-gray-300 text-gray-600 hover:bg-white">Non</button>
            </span>
          ) : (
            <button type="button" onClick={() => setConfirmeAnnuler(true)}
              className="flex items-center gap-1 px-2.5 py-1 rounded-md border border-red-200 text-red-700 hover:bg-red-50">
              <X size={12} /> Annuler
            </button>
          )}
        </div>
      )}
    </div>
  )
}
