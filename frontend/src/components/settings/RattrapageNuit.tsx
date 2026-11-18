/**
 * RattrapageNuit — « Rattrapage de nuit » (Paramètres › Maintenance, 18/11/2026).
 * ===========================================================================================
 * Remplace le workflow n8n « réindexation » : chaque nuit, Matothèque remet en file, par paquets
 * bornés, les documents en erreur, ceux qui ont du texte sans analyse IA, et ceux sans vecteurs.
 * Plafond 0 = rattrapage coupé (un réglage vidé reviendrait à son défaut, 02:00 / 100).
 */
import { useCallback, useEffect, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import { extractApiError, systemApi, type RattrapageNuit as Etat } from '../../api'
import { useToast } from '../common/Toast'

const STATUTS: Record<string, string> = {
  completed: 'fait', failed: 'en échec', pending: 'en attente', running: 'en cours', cancelled: 'annulé',
}

export function libelleDernier(etat: Etat | null): string {
  const d = etat?.dernier
  if (!d) return 'Aucun passage pour l\'instant.'
  const quand = d.date ? new Date(d.date).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '?'
  const statut = STATUTS[d.statut] ?? d.statut
  const r = d.resultat
  if (d.statut !== 'completed' || !r) return `Dernier passage : ${quand} (${statut}).`
  return `Dernier passage : ${quand} — ${r.erreurs ?? 0} erreur(s), ${r.analyse_ia ?? 0} analyse(s) IA, `
    + `${r.vecteurs ?? 0} document(s) sans vecteurs remis en file.`
}

export function RattrapageNuit() {
  const toast = useToast()
  const [etat, setEtat] = useState<Etat | null>(null)
  const [heure, setHeure] = useState('')
  const [plafond, setPlafond] = useState('')
  const [occupe, setOccupe] = useState(false)

  const lire = useCallback(() => {
    systemApi.rattrapageNuit().then(e => { setEtat(e); setHeure(e.heure); setPlafond(String(e.plafond)) })
      .catch(() => { /* section admin : l'erreur se voit déjà sur les autres réglages */ })
  }, [])
  useEffect(() => { lire() }, [lire])

  const plafondOk = /^\d+$/.test(plafond.trim()) && Number(plafond) <= 2000
  const modifie = !!etat && (heure !== etat.heure || plafond.trim() !== String(etat.plafond))

  const enregistrer = async () => {
    setOccupe(true)
    try {
      await systemApi.updateConfig({ rattrapage_nuit_heure: heure, rattrapage_nuit_plafond: plafond.trim() })
      toast.success(Number(plafond) === 0 ? 'Rattrapage de nuit coupé'
        : `Rattrapage de nuit : ${heure}, jusqu'à ${plafond.trim()} documents par volet`)
      lire()
    } catch (e) {
      toast.error(extractApiError(e, 'Enregistrement impossible'))
    } finally {
      setOccupe(false)
    }
  }

  const champ = 'text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white'
  return (
    <div className="flex items-start justify-between px-4 py-3 gap-4 border-t border-gray-100 flex-wrap">
      <div className="min-w-[16rem] flex-1">
        <p className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
          <RotateCcw size={14} className="text-indigo-500" /> Rattrapage de nuit
        </p>
        <p className="text-xs text-gray-400 mt-0.5">
          Une fois par nuit, remet en file les documents en erreur, ceux qui ont du texte sans analyse IA et
          ceux sans vecteurs (invisibles à la recherche par le sens). Un document retenté il y a moins de 7 jours
          attend. Plafond <strong>0</strong> = coupé.
        </p>
        <p className="text-xs mt-1 text-gray-600">{libelleDernier(etat)}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0 flex-wrap">
        <label className="text-xs text-gray-500 flex items-center gap-1">à
          <input type="time" value={heure} onChange={e => setHeure(e.target.value)}
            aria-label="Heure du rattrapage de nuit" className={champ} />
        </label>
        <label className="text-xs text-gray-500 flex items-center gap-1">plafond
          <input type="number" min={0} max={2000} value={plafond} onChange={e => setPlafond(e.target.value)}
            aria-label="Documents remis en file par volet" className={`${champ} w-20`} />
        </label>
        <button type="button" disabled={occupe || !modifie || !plafondOk || !heure} onClick={enregistrer}
          className="text-xs px-3 py-1.5 rounded-md bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-40">
          Enregistrer
        </button>
      </div>
    </div>
  )
}
