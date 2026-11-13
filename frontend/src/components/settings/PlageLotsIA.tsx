/**
 * PlageLotsIA — « Tâches de fond : plage horaire » (Paramètres › Maintenance, plan lots IA étape 4).
 * ===========================================================================================
 * Hors de la plage, le traitement de fond (enrichissement, vecteurs, lecture d'images) attend ;
 * « Créer », la discussion et la recherche restent servis. Vide = à toute heure (défaut).
 * Enregistrement explicite : une plage à moitié saisie ne doit jamais partir au serveur.
 */
import { useEffect, useState } from 'react'
import { Moon } from 'lucide-react'
import { extractApiError, systemApi } from '../../api'
import { erreurPlage, libellePlage } from '../../utils/plageLots'
import { useToast } from '../common/Toast'

interface Props {
  /** Plage en base au chargement des Paramètres (« » = aucune). */
  debut: string
  fin: string
  /** Prévenu après un enregistrement réussi. */
  onEnregistre: (debut: string, fin: string) => void
}

export function PlageLotsIA({ debut, fin, onEnregistre }: Props) {
  const toast = useToast()
  const [d, setD] = useState(debut)
  const [f, setF] = useState(fin)
  const [occupe, setOccupe] = useState(false)
  // La valeur en base arrive après le premier rendu (chargement asynchrone des réglages).
  useEffect(() => { setD(debut); setF(fin) }, [debut, fin])

  const erreur = erreurPlage(d, f)
  const modifie = d.trim() !== debut.trim() || f.trim() !== fin.trim()

  const enregistrer = async (nd: string, nf: string) => {
    const refus = erreurPlage(nd, nf)
    if (refus) { toast.error(refus); return }
    setOccupe(true)
    try {
      await systemApi.updateConfig({ lots_ia_plage_debut: nd.trim(), lots_ia_plage_fin: nf.trim() })
      setD(nd); setF(nf)
      onEnregistre(nd.trim(), nf.trim())
      toast.success(nd.trim() ? `Tâches de fond : de ${nd.trim()} à ${nf.trim()}` : 'Tâches de fond : à toute heure')
    } catch (e) {
      toast.error(extractApiError(e, 'Enregistrement impossible'))
    } finally {
      setOccupe(false)
    }
  }

  const champ = 'text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white'
  const bouton = 'text-xs px-2 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40'
  return (
    <div className="flex items-start justify-between px-4 py-3 gap-4 border-t border-gray-100 flex-wrap">
      <div className="min-w-[16rem] flex-1">
        <p className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
          <Moon size={14} className="text-indigo-500" /> Tâches de fond : plage horaire
        </p>
        <p className="text-xs text-gray-400 mt-0.5">
          Réserve l'enrichissement, les vecteurs et la lecture d'images à une plage (la nuit, par exemple),
          pour laisser la carte graphique libre le reste du temps. Effet immédiat (~10 s), sans redémarrage.
        </p>
        <p className={`text-xs mt-1 ${erreur ? 'text-red-600' : 'text-gray-600'}`}>{erreur ?? libellePlage(d, f)}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0 flex-wrap">
        <label className="text-xs text-gray-500 flex items-center gap-1">de
          <input type="time" value={d} onChange={e => setD(e.target.value)} aria-label="Début de la plage des tâches de fond" className={champ} />
        </label>
        <label className="text-xs text-gray-500 flex items-center gap-1">à
          <input type="time" value={f} onChange={e => setF(e.target.value)} aria-label="Fin de la plage des tâches de fond" className={champ} />
        </label>
        <button type="button" disabled={occupe || !modifie || !!erreur} onClick={() => enregistrer(d, f)}
          className="text-xs px-3 py-1.5 rounded-md bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-40">
          Enregistrer
        </button>
        <button type="button" disabled={occupe} onClick={() => enregistrer('22:00', '06:00')} className={bouton}
          title="Les tâches de fond ne tournent que de 22 h à 6 h">Nuit (22 h → 6 h)</button>
        <button type="button" disabled={occupe || (!debut && !fin)} onClick={() => enregistrer('', '')} className={bouton}
          title="Retirer la plage : les tâches de fond tournent à toute heure">Toujours</button>
      </div>
    </div>
  )
}
