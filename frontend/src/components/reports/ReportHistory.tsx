/**
 * ReportHistory — onglet « Historique » du panneau de résultat (page Créer)
 * =========================================================================
 * Liste les rapports archivés en base (persistants). Permet de :
 *   • rouvrir un rapport (clic → chargé dans l'onglet Rendu) ;
 *   • supprimer par cases : sélection individuelle + « tout sélectionner » ;
 *   • régler la purge automatique (tous les X jours) — enregistrée dans la config.
 */
import { useCallback, useEffect, useState } from 'react'
import { Trash2, FileClock, RefreshCw, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { rapportsApi, systemApi, extractApiError, type RapportResume } from '../../api'
import { useReportStore } from '../../stores/reportStore'
import { useToast } from '../common/Toast'

const PURGE_OPTIONS = [
  { j: 0, label: 'Jamais' },
  { j: 7, label: '7 jours' },
  { j: 30, label: '30 jours' },
  { j: 90, label: '90 jours' },
  { j: 365, label: '1 an' },
]

function dateCourte(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('fr', { day: '2-digit', month: '2-digit', year: '2-digit' }) +
    ' ' + d.toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' })
}

export default function ReportHistory({ onOuvert }: { onOuvert: () => void }) {
  const toast = useToast()
  const { loadRapport } = useReportStore()
  const [rapports, setRapports] = useState<RapportResume[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [purgeJours, setPurgeJours] = useState(0)
  const [busy, setBusy] = useState(false)

  const charger = useCallback(async () => {
    setLoading(true)
    try {
      const d = await rapportsApi.list(200)
      setRapports(d.rapports); setTotal(d.total)
      setSel(s => new Set([...s].filter(id => d.rapports.some(r => r.id === id))))
    } catch (e) { toast.error(extractApiError(e, 'Chargement de l\'historique impossible')) }
    finally { setLoading(false) }
  }, [toast])

  useEffect(() => { charger() }, [charger])
  useEffect(() => {
    systemApi.getConfig().then(c => setPurgeJours(Number(c.rapports_purge_jours?.valeur ?? 0) || 0)).catch(() => {})
  }, [])

  const toggle = (id: string) => setSel(s => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n
  })
  const toutSel = sel.size > 0 && sel.size === rapports.length
  const basculerTout = () => setSel(toutSel ? new Set() : new Set(rapports.map(r => r.id)))

  const ouvrir = async (id: string) => {
    try {
      const r = await rapportsApi.get(id)
      loadRapport(r.contenu)
      onOuvert()   // bascule le panneau sur l'onglet Rendu
    } catch (e) { toast.error(extractApiError(e, 'Ouverture impossible')) }
  }

  const supprimerSelection = async () => {
    if (sel.size === 0) return
    if (!confirm(`Supprimer ${sel.size} rapport(s) de l'historique ? Action définitive.`)) return
    setBusy(true)
    try {
      const { supprimes } = await rapportsApi.removeMany([...sel])
      toast.success(`${supprimes} rapport(s) supprimé(s)`)
      setSel(new Set()); await charger()
    } catch (e) { toast.error(extractApiError(e, 'Suppression impossible')) }
    finally { setBusy(false) }
  }

  const supprimerTout = async () => {
    if (total === 0) return
    if (!confirm(`Vider TOUT l'historique (${total} rapport(s)) ? Action définitive.`)) return
    setBusy(true)
    try {
      const { supprimes } = await rapportsApi.removeMany([], true)
      toast.success(`Historique vidé (${supprimes} rapport(s))`)
      setSel(new Set()); await charger()
    } catch (e) { toast.error(extractApiError(e, 'Suppression impossible')) }
    finally { setBusy(false) }
  }

  const changerPurge = async (j: number) => {
    setPurgeJours(j)
    try {
      await systemApi.updateConfig({ rapports_purge_jours: String(j) })
      toast.success(j === 0 ? 'Purge automatique désactivée' : `Purge auto : rapports de plus de ${j} jours`)
    } catch (e) { toast.error(extractApiError(e, 'Réglage impossible')) }
  }

  return (
    <div className="h-full flex flex-col p-3 gap-2">
      {/* Barre d'actions */}
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <label className="flex items-center gap-1.5 text-gray-600">
          <input type="checkbox" checked={toutSel} onChange={basculerTout} disabled={rapports.length === 0}
            className="w-3.5 h-3.5 accent-blue-600" />
          Tout sélectionner
        </label>
        <button type="button" onClick={supprimerSelection} disabled={sel.size === 0 || busy}
          className="flex items-center gap-1 px-2 py-1 rounded-md border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40">
          <Trash2 size={12} /> Supprimer{sel.size ? ` (${sel.size})` : ''}
        </button>
        <button type="button" onClick={supprimerTout} disabled={total === 0 || busy}
          className="px-2 py-1 rounded-md text-gray-500 hover:bg-gray-100 disabled:opacity-40">
          Tout vider
        </button>
        <button type="button" onClick={charger} title="Actualiser" className="p-1 text-gray-400 hover:text-gray-600">
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
        <span className="ml-auto flex items-center gap-1.5 text-gray-500">
          Purge auto
          <select value={purgeJours} onChange={e => changerPurge(Number(e.target.value))}
            title="Supprime automatiquement les rapports plus vieux que cette durée"
            className="border border-gray-200 rounded px-1.5 py-0.5 bg-white">
            {PURGE_OPTIONS.map(o => <option key={o.j} value={o.j}>{o.label}</option>)}
          </select>
        </span>
      </div>

      {/* Liste */}
      <div className="flex-1 overflow-y-auto min-h-0 -mr-1 pr-1">
        {loading && rapports.length === 0 && (
          <p className="text-xs text-gray-400 py-4 flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Chargement…</p>
        )}
        {!loading && rapports.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center text-gray-400 gap-2">
            <FileClock size={28} className="opacity-40" />
            <p className="text-xs">Aucun rapport archivé.<br />Les rapports générés apparaîtront ici.</p>
          </div>
        )}
        {rapports.map(r => (
          <div key={r.id}
            className={clsx('flex items-start gap-2 py-1.5 px-1 rounded text-xs border-b border-gray-100',
              sel.has(r.id) ? 'bg-blue-50' : 'hover:bg-gray-50')}>
            <input type="checkbox" checked={sel.has(r.id)} onChange={() => toggle(r.id)} onClick={e => e.stopPropagation()}
              className="w-3.5 h-3.5 accent-blue-600 mt-0.5 shrink-0" aria-label={`Sélectionner ${r.titre}`} />
            <button type="button" onClick={() => ouvrir(r.id)} className="flex-1 min-w-0 text-left">
              <p className="font-medium text-gray-700 truncate">{r.titre}</p>
              <p className="text-gray-400 truncate">
                {dateCourte(r.created_at)} · {r.modele || '—'} · {r.sources.length} source{r.sources.length > 1 ? 's' : ''} · {r.nb_caracteres.toLocaleString('fr')} car.
              </p>
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
