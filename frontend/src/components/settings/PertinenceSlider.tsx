/**
 * PertinenceSlider — curseur « Exigence : souple ↔ stricte » (Phase 3 du seuil de pertinence).
 *
 * La recherche masque les documents jugés hors-sujet via deux seuils de similarité cosinus
 * (`search_cos_haut` / `search_cos_bas`, cf. backend `services/pertinence.py`). Exposer ces
 * deux nombres bruts n'aurait aucun sens pour l'utilisateur : on présente un SEUL curseur à
 * cinq crans, chacun mappant sur un couple de seuils calibré. Le cran « Équilibré » reprend la
 * calibration par défaut du corpus NAS. Auto-enregistrement immédiat (effet sur recherche + Assistant).
 */
import { useEffect, useState } from 'react'
import { Check, RotateCcw, Sliders } from 'lucide-react'
import { systemApi } from '../../api'

type Niveau = { cle: string; label: string; haut: number; bas: number; aide: string }

// Couples (haut, bas) centrés sur la calibration par défaut (0.72 / 0.65). Plus on va vers la
// droite, plus les seuils montent → moins de documents passent, mais aussi plus de « aucun résultat ».
const NIVEAUX: Niveau[] = [
  { cle: 'tres-souple',  label: 'Très souple',  haut: 0.68, bas: 0.60, aide: 'Affiche large. Peu de « aucun document », mais des pièces plus éloignées du sujet remontent.' },
  { cle: 'souple',       label: 'Souple',       haut: 0.70, bas: 0.62, aide: 'Un peu plus permissif que l’équilibré — utile si des documents attendus sont masqués.' },
  { cle: 'equilibre',    label: 'Équilibré',    haut: 0.72, bas: 0.65, aide: 'Réglage recommandé, calibré sur le corpus. Bon compromis bruit / rappel.' },
  { cle: 'stricte',      label: 'Stricte',      haut: 0.74, bas: 0.68, aide: 'Ne garde que les correspondances nettes. Plus de « aucun document », moins de bruit.' },
  { cle: 'tres-stricte', label: 'Très stricte', haut: 0.77, bas: 0.71, aide: 'Uniquement les réponses franches. Beaucoup de « aucun document » — à réserver aux corpus riches.' },
]

const DEFAUT = 2   // « Équilibré »
const EPS = 0.005  // tolérance de correspondance d'un couple à un cran

function niveauPour(haut: number, bas: number): number {
  const i = NIVEAUX.findIndex(n => Math.abs(n.haut - haut) < EPS && Math.abs(n.bas - bas) < EPS)
  return i   // -1 = réglage personnalisé (hors presets)
}

export default function PertinenceSlider() {
  const [idx, setIdx] = useState(DEFAUT)
  const [perso, setPerso] = useState(false)   // les seuils en base ne correspondent à aucun cran
  const [charge, setCharge] = useState(false)
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  useEffect(() => {
    systemApi.getConfig()
      .then(c => {
        const haut = parseFloat(c.search_cos_haut?.valeur ?? '')
        const bas = parseFloat(c.search_cos_bas?.valeur ?? '')
        if (Number.isFinite(haut) && Number.isFinite(bas)) {
          const n = niveauPour(haut, bas)
          if (n >= 0) setIdx(n)
          else {
            setPerso(true)
            // Positionne le curseur sur le cran le plus proche (par le seuil haut) sans écraser la base.
            setIdx(NIVEAUX.reduce((best, n2, j) => Math.abs(n2.haut - haut) < Math.abs(NIVEAUX[best].haut - haut) ? j : best, 0))
          }
        }
      })
      .catch(() => {})
      .finally(() => setCharge(true))
  }, [])

  const appliquer = async (i: number) => {
    setIdx(i)
    setPerso(false)
    setStatus('saving')
    try {
      await systemApi.updateConfig({
        search_cos_haut: String(NIVEAUX[i].haut),
        search_cos_bas: String(NIVEAUX[i].bas),
      })
      setStatus('saved')
    } catch {
      setStatus('error')
    }
  }

  const n = NIVEAUX[idx]

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
      <div className="flex items-start gap-2">
        <Sliders size={16} className="text-blue-600 shrink-0 mt-0.5" />
        <p className="text-xs text-gray-500 leading-relaxed">
          Contrôle à quel point la recherche (et l’Assistant IA) écarte les documents jugés hors-sujet.
          Plus c’est <strong>strict</strong>, moins de bruit mais plus de « aucun document pertinent ».
          Un bouton <em>« Afficher quand même »</em> reste toujours disponible côté recherche.
        </p>
      </div>

      <div>
        <input
          type="range" min={0} max={NIVEAUX.length - 1} step={1} value={idx}
          disabled={!charge}
          onChange={e => appliquer(Number(e.target.value))}
          aria-label="Exigence de pertinence"
          className="w-full accent-blue-600 cursor-pointer disabled:opacity-50"
        />
        <div className="flex justify-between mt-1 px-0.5">
          {NIVEAUX.map((niv, i) => (
            <button
              key={niv.cle} type="button" disabled={!charge}
              onClick={() => appliquer(i)}
              className={`text-[10px] leading-tight text-center transition-colors ${
                i === idx && !perso ? 'text-blue-700 font-semibold' : 'text-gray-400 hover:text-gray-600'
              }`}
              style={{ width: '20%' }}
            >
              {niv.label}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-gray-50 border border-gray-100 rounded-md px-3 py-2.5 text-xs text-gray-600 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-gray-800">
            {perso ? 'Personnalisé' : n.label}
          </span>
          <span className="font-mono text-[11px] text-gray-400">
            (haut {n.haut.toFixed(2)} · bas {n.bas.toFixed(2)})
          </span>
          {perso && (
            <span className="text-[10px] text-amber-600">seuils modifiés hors des crans</span>
          )}
        </div>
        <p className="text-gray-500">{n.aide}</p>
      </div>

      <div className="flex items-center justify-between gap-2 text-xs h-4">
        <button
          type="button" onClick={() => appliquer(DEFAUT)} disabled={!charge || (idx === DEFAUT && !perso)}
          className="flex items-center gap-1 text-gray-400 hover:text-blue-600 disabled:opacity-40 disabled:hover:text-gray-400"
        >
          <RotateCcw size={12} /> Rétablir l’équilibré
        </button>
        {status === 'saving' && <span className="text-gray-400">Enregistrement…</span>}
        {status === 'saved' && <span className="text-green-600 flex items-center gap-1"><Check size={12} /> Enregistré</span>}
        {status === 'error' && <span className="text-red-500">Échec de l’enregistrement</span>}
      </div>
    </div>
  )
}
