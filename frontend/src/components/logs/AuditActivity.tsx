/**
 * AuditActivity — vue « Traçabilité » (observabilité Phase 2)
 * ==========================================================
 * Affiche le journal d'activité métier (`audit_events`) : chaque opération (indexation, synchro,
 * génération…) tracée de bout en bout par un `correlation_id` reliant les couches UI → API →
 * worker, avec acteur, statut, durée. Filtre par action ; clic sur une ligne → chaîne complète
 * de la corrélation (tout l'enchaînement d'une même opération).
 */
import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, CheckCircle2, XCircle, Ban, Clock, ChevronRight } from 'lucide-react'
import { clsx } from 'clsx'
import { auditApi, type AuditEvent } from '../../api'

const ACTION_LABEL: Record<string, string> = {
  indexation: 'Indexation', sync_source: 'Synchronisation', generate_report: 'Génération de rapport',
  analyze: 'Analyse de contenu', enrich: 'Enrichissement IA', fill_template: 'Remplissage modèle',
  presentation: 'Présentation', reorg_apply: 'Réorganisation', reorg_undo: 'Annulation réorg',
  index_connector: 'Indexation connecteur', index_wiki: 'Indexation wiki', demo: 'Démo',
}
const lab = (a: string) => ACTION_LABEL[a] ?? a

function StatutIcone({ s }: { s: string }) {
  if (s === 'success') return <CheckCircle2 size={13} className="text-green-500 shrink-0" />
  if (s === 'error') return <XCircle size={13} className="text-red-500 shrink-0" />
  if (s === 'cancelled') return <Ban size={13} className="text-gray-400 shrink-0" />
  if (s === 'start' || s === 'queued') return <Clock size={13} className="text-blue-500 shrink-0" />
  return <ChevronRight size={13} className="text-gray-400 shrink-0" />
}

function heure(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'medium' })
}
function duree(ms: number | null): string {
  if (ms == null) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`
}

export default function AuditActivity() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [actions, setActions] = useState<string[]>([])
  const [filtre, setFiltre] = useState('')
  const [loading, setLoading] = useState(false)
  const [corr, setCorr] = useState<string | null>(null)   // corrélation dépliée (chaîne complète)

  const charger = useCallback(async () => {
    setLoading(true)
    try {
      const [ev, ac] = await Promise.all([
        auditApi.list({ action: filtre || undefined, limit: 300 }),
        auditApi.actions().catch(() => []),
      ])
      setEvents(ev); setActions(ac)
    } catch { /* silencieux */ } finally { setLoading(false) }
  }, [filtre])

  useEffect(() => { charger() }, [charger])

  // Événements de la corrélation dépliée (chaîne chronologique).
  const [chaine, setChaine] = useState<AuditEvent[]>([])
  useEffect(() => {
    if (!corr) { setChaine([]); return }
    auditApi.list({ correlation_id: corr, limit: 100 }).then(setChaine).catch(() => setChaine([]))
  }, [corr])

  return (
    <div className="pt-1 space-y-2">
      {/* Barre : filtre par action + rafraîchir */}
      <div className="flex items-center gap-2 text-xs">
        <select value={filtre} onChange={e => setFiltre(e.target.value)}
          className="border border-gray-200 rounded px-2 py-1 bg-white text-gray-700">
          <option value="">Toutes les actions</option>
          {actions.map(a => <option key={a} value={a}>{lab(a)}</option>)}
        </select>
        <button type="button" onClick={charger} title="Actualiser" className="p-1 text-gray-400 hover:text-gray-600">
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
        <span className="text-gray-400 ml-auto">{events.length} événement(s)</span>
      </div>

      {events.length === 0 ? (
        <p className="text-xs text-gray-400 py-2">Aucun événement d'audit. Les opérations (indexation, synchro, génération…) apparaîtront ici.</p>
      ) : (
        <ul className="divide-y divide-gray-100 max-h-96 overflow-auto">
          {events.map(e => (
            <li key={e.id}>
              <button type="button"
                onClick={() => setCorr(corr === e.correlation_id ? null : e.correlation_id)}
                className={clsx('w-full flex items-center gap-2 py-1.5 text-xs text-left hover:bg-gray-50 rounded px-1',
                  corr && corr === e.correlation_id && 'bg-blue-50/50')}>
                <StatutIcone s={e.statut} />
                <span className="font-medium text-gray-700 w-36 shrink-0 truncate">{lab(e.action)}</span>
                <span className="text-gray-400 w-14 shrink-0">{e.acteur}</span>
                <span className="text-gray-500 flex-1 truncate">{e.cible || e.message || ''}</span>
                <span className="text-gray-400 shrink-0 tabular-nums">{duree(e.duree_ms)}</span>
                <span className="text-gray-300 shrink-0 w-32 text-right truncate">{heure(e.created_at)}</span>
              </button>
              {/* Chaîne complète de la corrélation (dépliée) */}
              {corr && corr === e.correlation_id && chaine.length > 0 && (
                <div className="ml-6 mb-1.5 pl-3 border-l-2 border-blue-200 space-y-0.5">
                  {chaine.map(c => (
                    <div key={c.id} className="flex items-center gap-2 text-[11px] text-gray-500">
                      <StatutIcone s={c.statut} />
                      <span className="w-14 shrink-0">{c.acteur}</span>
                      <span className="w-16 shrink-0">{c.statut}</span>
                      <span className="flex-1 truncate">{c.message || c.cible || ''}</span>
                      <span className="tabular-nums">{duree(c.duree_ms)}</span>
                      <span className="text-gray-300">{heure(c.created_at)}</span>
                    </div>
                  ))}
                  <div className="text-[10px] text-gray-300 pt-0.5">corrélation {corr}</div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
