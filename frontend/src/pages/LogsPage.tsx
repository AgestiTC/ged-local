/**
 * LogsPage — Journaux & historique (sections pliables).
 *  1. Activité (qui fait quoi)   → tâches en cours + récentes
 *  2. Journal (que s'est-il passé) → historique des tâches terminées
 *  3. Debug (technique)          → dernières lignes du log applicatif
 * + purge de l'historique (fenêtre de confirmation, jamais les tâches en cours).
 */
import { useEffect, useState } from 'react'
import { Activity, ScrollText, Bug, RefreshCw, Trash2, Loader2, CheckCircle2, XCircle, Ban } from 'lucide-react'
import CollapsibleSection from '../components/common/CollapsibleSection'
import { jobsApi, logsApi, type JobInfo } from '../api'
import { useToast } from '../components/common/Toast'

const LABEL: Record<string, string> = {
  enrich: 'Analyse IA', analyze: 'Analyse du contenu', extraction: 'Analyse complète',
  presentation: 'Présentation', fill_template: 'Remplissage modèle', indexation: 'Indexation', demo: 'Démo',
}
const lab = (t: string) => LABEL[t] ?? t
const actif = (s: string) => s === 'pending' || s === 'running'

function dt(s: string | null | undefined) {
  if (!s) return '—'
  const d = new Date(s)
  return isNaN(d.getTime()) ? '—' : d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
}
function StatutIcone({ s }: { s: string }) {
  if (s === 'completed') return <CheckCircle2 size={13} className="text-green-500" />
  if (s === 'failed') return <XCircle size={13} className="text-red-500" />
  if (s === 'cancelled') return <Ban size={13} className="text-gray-400" />
  return <Loader2 size={13} className="text-blue-500 animate-spin" />
}

export default function LogsPage() {
  const toast = useToast()
  const [jobs, setJobs] = useState<JobInfo[]>([])
  const [logs, setLogs] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [purge, setPurge] = useState<null | { total: number; anciens: number }>(null)  // fenêtre de confirmation
  const [purging, setPurging] = useState(false)

  const charger = () => {
    setLoading(true)
    Promise.all([
      jobsApi.list({ limit: 200 }).then(r => r.jobs).catch(() => []),
      logsApi.tail(300).then(r => r.lines).catch(() => []),
    ]).then(([j, l]) => { setJobs(j); setLogs(l) }).finally(() => setLoading(false))
  }
  useEffect(charger, [])

  const ouvrirPurge = async () => {
    try { const c = await jobsApi.purgeCount(365); setPurge({ total: c.total_termines, anciens: c.anciens }) }
    catch { setPurge({ total: 0, anciens: 0 }) }
  }
  const lancerPurge = async (scope: 'all' | 'older_than') => {
    setPurging(true)
    try {
      const r = await jobsApi.purge(scope, 365)
      toast.success(`${r.supprimes} tâche(s) purgée(s)`) ; setPurge(null) ; charger()
    } catch { toast.error('Purge impossible') }
    finally { setPurging(false) }
  }

  const enCours = jobs.filter(j => actif(j.statut))
  const historique = jobs.filter(j => !actif(j.statut))

  return (
    <div className="max-w-4xl mx-auto p-6 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold text-gray-800 flex items-center gap-2">🧾 Journaux &amp; historique</h1>
        <div className="flex items-center gap-2">
          <button type="button" onClick={charger} disabled={loading}
            className="flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Rafraîchir
          </button>
          <button type="button" onClick={ouvrirPurge}
            className="flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border border-red-200 text-red-600 hover:bg-red-50">
            <Trash2 size={13} /> Purger l'historique
          </button>
        </div>
      </div>

      {/* 1. Activité — qui fait quoi */}
      <CollapsibleSection id="logs-activite" defaultOpen icon={<Activity size={16} className="text-blue-600" />}
        title={`Activité — qui fait quoi${enCours.length ? ` (${enCours.length} en cours)` : ''}`}>
        <div className="pt-1">
          {enCours.length === 0 ? (
            <p className="text-xs text-gray-400">Aucune tâche en cours.</p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {enCours.map(j => (
                <li key={j.id} className="flex items-center gap-2 py-1.5 text-xs">
                  <StatutIcone s={j.statut} />
                  <span className="font-medium text-gray-700">{lab(j.type)}</span>
                  <span className="text-gray-400 flex-1 truncate">{j.progress_message}</span>
                  <span className="text-gray-400">{j.progress}%</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CollapsibleSection>

      {/* 2. Journal — que s'est-il passé (historique) */}
      <CollapsibleSection id="logs-journal" defaultOpen icon={<ScrollText size={16} className="text-amber-600" />}
        title={`Journal — que s'est-il passé (${historique.length})`}>
        <div className="pt-1">
          {loading ? <div className="flex justify-center py-4"><Loader2 size={16} className="animate-spin text-gray-400" /></div>
            : historique.length === 0 ? <p className="text-xs text-gray-400">Historique vide.</p> : (
            <ul className="divide-y divide-gray-100 max-h-96 overflow-auto">
              {historique.map(j => (
                <li key={j.id} className="flex items-center gap-2 py-1.5 text-xs">
                  <StatutIcone s={j.statut} />
                  <span className="font-medium text-gray-700 w-40 shrink-0 truncate">{lab(j.type)}</span>
                  <span className="text-gray-400 flex-1 truncate">{j.erreur || j.progress_message}</span>
                  <span className="text-gray-400 shrink-0">{dt(j.completed_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CollapsibleSection>

      {/* 3. Debug — technique */}
      <CollapsibleSection id="logs-debug" defaultOpen={false} icon={<Bug size={16} className="text-gray-500" />}
        title="Debug — log applicatif">
        <div className="pt-1">
          {logs.length === 0 ? <p className="text-xs text-gray-400">Aucune ligne de log (fichier non configuré ?).</p> : (
            <pre className="text-[11px] text-gray-600 bg-gray-900/95 text-gray-200 rounded-lg p-3 max-h-96 overflow-auto whitespace-pre-wrap font-mono">
              {logs.join('\n')}
            </pre>
          )}
        </div>
      </CollapsibleSection>

      {/* Fenêtre de confirmation de purge */}
      {purge && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => !purging && setPurge(null)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2"><Trash2 size={18} className="text-red-600" /> Purger l'historique des tâches</h2>
            <p className="text-sm text-gray-600 mb-4">
              Supprime l'historique des tâches <strong>terminées</strong> (les tâches en cours ne sont
              jamais touchées). <strong>Action irréversible.</strong>
            </p>
            <div className="text-xs text-gray-500 mb-4 space-y-1">
              <div>Historique total : <strong>{purge.total}</strong> tâche(s)</div>
              <div>Plus vieilles que 365 jours : <strong>{purge.anciens}</strong></div>
            </div>
            <div className="flex justify-end gap-2 flex-wrap">
              <button type="button" onClick={() => setPurge(null)} disabled={purging}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">Annuler</button>
              <button type="button" onClick={() => lancerPurge('older_than')} disabled={purging || purge.anciens === 0}
                className="px-3 py-2 text-sm rounded-lg border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40">
                Purger &gt; 365 j ({purge.anciens})
              </button>
              <button type="button" onClick={() => lancerPurge('all')} disabled={purging || purge.total === 0}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-40">
                {purging ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />} Tout purger ({purge.total})
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
