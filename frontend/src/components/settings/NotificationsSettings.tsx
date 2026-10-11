/**
 * NotificationsSettings — tuile « Notifications » des Paramètres (11/10/2026).
 * ============================================================================
 * Fréquence du bilan « idées d'évolution » (mensuel · trimestriel · désactivé), bilan à la demande,
 * et historique des notifications (lire, supprimer). Le bilan est rédigé par l'IA locale à partir
 * des instructions complémentaires données pour analyser les documents de référence.
 */
import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Loader2, Sparkles, Trash2 } from 'lucide-react'
import { clsx } from 'clsx'
import { notificationsApi, suivreJob, systemApi, type NotificationItem } from '../../api'
import { useToast } from '../common/Toast'

const FREQUENCES = [
  { valeur: 'mensuel', libelle: 'Mensuel' },
  { valeur: 'trimestriel', libelle: 'Trimestriel' },
  { valeur: 'desactive', libelle: 'Désactivé' },
]

export default function NotificationsSettings() {
  const [frequence, setFrequence] = useState('mensuel')
  const [items, setItems] = useState<NotificationItem[]>([])
  const [ouverte, setOuverte] = useState<string | null>(null)
  const [generation, setGeneration] = useState(false)
  const toast = useToast()

  const charger = () => notificationsApi.list().then(r => setItems(r.notifications)).catch(() => {})

  useEffect(() => {
    systemApi.getConfig()
      .then(c => setFrequence(c.notif_idees_frequence?.valeur || 'mensuel'))
      .catch(() => {})
    charger()
  }, [])

  const changerFrequence = async (valeur: string) => {
    setFrequence(valeur)
    try {
      await systemApi.updateConfig({ notif_idees_frequence: valeur })
      toast.success('Fréquence enregistrée')
    } catch {
      toast.error('Enregistrement impossible')
    }
  }

  const genererMaintenant = async () => {
    setGeneration(true)
    try {
      const { job_id } = await notificationsApi.genererIdees()
      const job = await suivreJob(job_id)
      const resultat = (job.resultat ?? {}) as { statut?: string; message?: string }
      if (job.statut !== 'completed') toast.error(`Bilan impossible : ${job.erreur ?? 'Ollama ?'}`)
      else if (resultat.statut === 'rien') toast.success(resultat.message ?? 'Rien à analyser sur la période')
      else { toast.success('Bilan rédigé : il est dans la cloche 🔔'); charger() }
    } catch {
      toast.error('Bilan impossible (Ollama ?)')
    } finally {
      setGeneration(false)
    }
  }

  const supprimer = async (id: string) => {
    try {
      await notificationsApi.supprimer(id)
      setItems(prev => prev.filter(n => n.id !== id))
    } catch {
      toast.error('Suppression impossible')
    }
  }

  return (
    <div className="space-y-4 text-sm">
      <div className="rounded-lg border border-gray-200 p-3 space-y-2">
        <p className="font-medium text-gray-800">💡 Bilan « idées d'évolution »</p>
        <p className="text-xs text-gray-500 leading-relaxed">
          L'IA locale relit les <strong>instructions complémentaires</strong> que vous donnez pour analyser vos
          documents de référence (CCTP, règlement…), repère ce qui revient, et propose des idées d'évolution et des
          prompts à enregistrer. Le bilan arrive dans la cloche 🔔 de l'en-tête. 100 % local.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-gray-600">Fréquence</label>
          <select value={frequence} onChange={e => changerFrequence(e.target.value)}
            className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
            {FREQUENCES.map(f => <option key={f.valeur} value={f.valeur}>{f.libelle}</option>)}
          </select>
          <button type="button" onClick={genererMaintenant} disabled={generation}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border border-violet-200 bg-violet-50 text-violet-700 hover:bg-violet-100 disabled:opacity-60">
            {generation ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
            {generation ? 'Rédaction du bilan…' : 'Générer le bilan maintenant'}
          </button>
        </div>
      </div>

      <div className="space-y-2">
        <p className="font-medium text-gray-800">Historique</p>
        {items.length === 0 ? (
          <p className="text-xs text-gray-400">Aucune notification pour l'instant.</p>
        ) : (
          <ul className="space-y-1.5">
            {items.map(n => (
              <li key={n.id} className="rounded-lg border border-gray-200">
                <div className="flex items-center gap-2 px-3 py-2">
                  <button type="button" onClick={() => setOuverte(ouverte === n.id ? null : n.id)}
                    className={clsx('flex-1 min-w-0 text-left truncate text-xs', n.lu ? 'text-gray-600' : 'text-gray-900 font-medium')}>
                    {n.titre}
                  </button>
                  {n.created_at && (
                    <span className="text-xs text-gray-400 shrink-0">{new Date(n.created_at).toLocaleDateString('fr-FR')}</span>
                  )}
                  <button type="button" onClick={() => supprimer(n.id)} title="Supprimer"
                    className="p-1 text-gray-400 hover:text-red-500 shrink-0">
                    <Trash2 size={13} />
                  </button>
                </div>
                {ouverte === n.id && (
                  <div className="px-3 pb-3 prose prose-sm max-w-none border-t border-gray-100 pt-2">
                    <ReactMarkdown>{n.contenu}</ReactMarkdown>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
