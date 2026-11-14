/**
 * PreferencesNotificationsSection — « Mes alertes » (étape 11 du rangement).
 * ===========================================================================
 * Les préférences de LA personne connectée (ou du poste local, authentification éteinte) : quelles
 * alertes recevoir, les seuils (place disque, croissance d'un dossier) et des heures de silence —
 * pendant lesquelles les notifications attendent la fin du silence pour apparaître. Les réglages
 * d'une personne ne touchent jamais ceux d'une autre (une ligne par personne côté serveur).
 */
import { useEffect, useState } from 'react'
import { BellRing, Loader2, Save } from 'lucide-react'
import { notificationsApi, type PreferencesNotifications } from '../../api'
import { useToast } from '../common/Toast'

export default function PreferencesNotificationsSection() {
  const [prefs, setPrefs] = useState<PreferencesNotifications | null>(null)
  const [erreur, setErreur] = useState(false)
  const [enregistrement, setEnregistrement] = useState(false)
  const toast = useToast()

  useEffect(() => {
    notificationsApi.preferences().then(setPrefs).catch(() => setErreur(true))
  }, [])

  if (erreur) return <p className="text-xs text-gray-400">Préférences d'alerte indisponibles.</p>
  if (!prefs) return <p className="text-xs text-gray-400 flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Chargement…</p>
  if (prefs.alertes.length === 0) return null   // rien à régler pour ce rôle

  const basculer = (type: string) =>
    setPrefs({ ...prefs, alertes: prefs.alertes.map(a => (a.type === type ? { ...a, active: !a.active } : a)) })
  const nombre = (cle: 'seuil_disque_pct' | 'seuil_croissance_pct' | 'seuil_croissance_gio', v: string) =>
    setPrefs({ ...prefs, [cle]: Math.max(0, parseInt(v, 10) || 0) })

  const silence = !!(prefs.silence_debut && prefs.silence_fin)

  const enregistrer = async () => {
    setEnregistrement(true)
    try {
      const r = await notificationsApi.enregistrerPreferences({
        ...prefs,
        alertes: Object.fromEntries(prefs.alertes.map(a => [a.type, a.active])),
        silence_debut: silence ? prefs.silence_debut : null,
        silence_fin: silence ? prefs.silence_fin : null,
      })
      setPrefs(r)
      toast.success('Préférences enregistrées')
    } catch {
      toast.error('Enregistrement impossible (valeurs hors limites ?)')
    } finally {
      setEnregistrement(false)
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 p-3 space-y-3">
      <p className="font-medium text-gray-800 flex items-center gap-1.5"><BellRing size={14} className="text-rose-500" /> Mes alertes</p>
      <p className="text-xs text-gray-500 leading-relaxed">
        Ce que la cloche 🔔 vous signale. Ces réglages ne concernent que vous.
      </p>

      <ul className="space-y-1.5">
        {prefs.alertes.map(a => (
          <li key={a.type}>
            <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
              <input type="checkbox" checked={a.active} onChange={() => basculer(a.type)} className="rounded" />
              {a.libelle}
            </label>
            {a.type === 'rangement_disque' && a.active && (
              <div className="ml-6 mt-1 flex items-center gap-1.5 text-xs text-gray-500">
                au-delà de
                <input type="number" min={50} max={99} value={prefs.seuil_disque_pct}
                  onChange={e => nombre('seuil_disque_pct', e.target.value)}
                  className="w-16 px-1.5 py-0.5 border border-gray-300 rounded" aria-label="Seuil d'occupation du disque en %" />
                % d'occupation
              </div>
            )}
            {a.type === 'rangement_croissance' && a.active && (
              <div className="ml-6 mt-1 flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
                un dossier qui grossit d'au moins
                <input type="number" min={5} max={1000} value={prefs.seuil_croissance_pct}
                  onChange={e => nombre('seuil_croissance_pct', e.target.value)}
                  className="w-16 px-1.5 py-0.5 border border-gray-300 rounded" aria-label="Croissance minimale en %" />
                % et de
                <input type="number" min={0} max={10000} value={prefs.seuil_croissance_gio}
                  onChange={e => nombre('seuil_croissance_gio', e.target.value)}
                  className="w-16 px-1.5 py-0.5 border border-gray-300 rounded" aria-label="Croissance minimale en Gio" />
                Gio entre deux scans
              </div>
            )}
          </li>
        ))}
      </ul>

      <div className="space-y-1.5">
        <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
          <input type="checkbox" checked={silence} className="rounded"
            onChange={() => setPrefs(silence ? { ...prefs, silence_debut: null, silence_fin: null }
              : { ...prefs, silence_debut: '22:00', silence_fin: '07:00' })} />
          Heures de silence
        </label>
        {silence && (
          <div className="ml-6 flex items-center gap-1.5 text-xs text-gray-500">
            de
            <input type="time" value={prefs.silence_debut ?? ''} onChange={e => setPrefs({ ...prefs, silence_debut: e.target.value })}
              className="px-1.5 py-0.5 border border-gray-300 rounded" aria-label="Début du silence" />
            à
            <input type="time" value={prefs.silence_fin ?? ''} onChange={e => setPrefs({ ...prefs, silence_fin: e.target.value })}
              className="px-1.5 py-0.5 border border-gray-300 rounded" aria-label="Fin du silence" />
            <span className="text-gray-400">— les alertes apparaissent à la fin du silence</span>
          </div>
        )}
      </div>

      <button type="button" onClick={enregistrer} disabled={enregistrement}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
        {enregistrement ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Enregistrer
      </button>
    </div>
  )
}
