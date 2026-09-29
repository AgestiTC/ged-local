/**
 * IAEchecs — appels IA en échec, par modèle
 * =========================================
 * Un modèle qui répond 400/404, qui expire ou qui rend une réponse inexploitable était absorbé
 * par le repli « même famille » : l'enrichissement passait au modèle suivant et rien ne le
 * disait. Ici, on le voit : combien, de quelle nature, et le dernier message d'erreur.
 */
import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react'
import { systemApi, type IAEchecsResume, type IAEchecNature } from '../../api'

const NATURE: Record<string, string> = {
  http: 'HTTP', delai: 'délai dépassé', connexion: 'injoignable', vide: 'réponse vide',
  inexploitable: 'réponse inexploitable', non_json: 'réponse non JSON', autre: 'autre',
}
const FENETRES = [{ h: 24, label: '24 h' }, { h: 24 * 7, label: '7 jours' }, { h: 24 * 30, label: '30 jours' }]

function libelleNature(n: IAEchecNature): string {
  const base = NATURE[n.nature] ?? n.nature
  return n.nature === 'http' && n.code_http ? `${base} ${n.code_http}` : base
}

function quand(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
}

export default function IAEchecs() {
  const [heures, setHeures] = useState(24)
  const [data, setData] = useState<IAEchecsResume | null>(null)
  const [erreur, setErreur] = useState(false)
  const [loading, setLoading] = useState(false)

  const charger = useCallback(async () => {
    setLoading(true)
    try { setData(await systemApi.iaEchecs(heures)); setErreur(false) }
    catch { setErreur(true) }
    finally { setLoading(false) }
  }, [heures])

  useEffect(() => { charger() }, [charger])

  return (
    <div className="pt-1 space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <select value={heures} onChange={e => setHeures(Number(e.target.value))}
          className="border border-gray-200 rounded px-2 py-1 bg-white text-gray-700">
          {FENETRES.map(f => <option key={f.h} value={f.h}>{f.label}</option>)}
        </select>
        <button type="button" onClick={charger} title="Actualiser" className="p-1 text-gray-400 hover:text-gray-600">
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
        {data && <span className="text-gray-400 ml-auto">{data.total} appel(s) en échec</span>}
      </div>

      {erreur ? (
        <p className="text-red-500">Impossible de lire les échecs IA — le serveur ne répond pas.</p>
      ) : data && data.modeles.length === 0 ? (
        <p className="flex items-center gap-1.5 text-green-600">
          <CheckCircle2 size={13} /> Aucun appel IA en échec sur cette période.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {data?.modeles.map(m => (
            <li key={m.modele} className="py-1.5 space-y-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <AlertTriangle size={13} className="text-amber-500 shrink-0" />
                <span className="font-mono font-medium text-gray-700">{m.modele}</span>
                <span className="text-gray-500">{m.total} échec(s)</span>
                {m.natures.map(n => (
                  <span key={`${n.nature}-${n.code_http}`}
                    className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">
                    {libelleNature(n)} × {n.nombre}
                  </span>
                ))}
                <span className="text-gray-300 ml-auto">{quand(m.dernier)}</span>
              </div>
              {m.dernier_message && (
                <p className="ml-5 text-gray-500 truncate" title={m.dernier_message}>
                  {m.derniere_operation ? `${m.derniere_operation} — ` : ''}{m.dernier_message}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
