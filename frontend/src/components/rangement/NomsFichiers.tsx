/**
 * Rangement › Carte — « Noms de fichiers » : combien de fichiers sont mal nommés, par catégorie et par
 * raison, avec des exemples. D'après Paramètres › Rangement — règles de nommage (16/11/2026).
 * Lecture seule : rien n'est renommé d'ici.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { inventaireApi, type BilanNommage } from '../../api/inventaire'
import { nombre, tailleLisible } from '../../utils/formatInventaire'
import Barre from './Barre'

export function pourcent(part: number, total: number): number {
  return total > 0 ? Math.round((part / total) * 100) : 0
}

export default function NomsFichiers({ emplacementId, chemin, relecture }: { emplacementId: number; chemin: string; relecture: number }) {
  const [bilan, setBilan] = useState<BilanNommage | null>(null)
  const [erreur, setErreur] = useState(false)

  useEffect(() => {
    let annule = false
    setBilan(null); setErreur(false)
    inventaireApi.nommage(emplacementId, chemin)
      .then(b => { if (!annule) setBilan(b) })
      .catch(() => { if (!annule) setErreur(true) })
    return () => { annule = true }
  }, [emplacementId, chemin, relecture])

  return (
    <div className="border border-gray-200 rounded-lg p-3 min-w-0 space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">Noms de fichiers</h3>
        <Link to="/settings?section=set-nommage" className="text-xs text-blue-600 hover:underline">Règles de nommage</Link>
      </div>
      {erreur && <p className="text-xs text-gray-500">Statistiques des noms indisponibles.</p>}
      {!erreur && bilan === null && <Loader2 size={16} className="animate-spin text-gray-400" />}
      {bilan && bilan.analyses === 0 && <p className="text-xs text-gray-500">Aucun fichier à examiner ici.</p>}
      {bilan && bilan.analyses > 0 && (
        <>
          <p className="text-sm">
            <span className={bilan.mal_nommes ? 'font-semibold text-amber-700' : 'font-semibold text-green-700'}>
              {nombre(bilan.mal_nommes)} mal nommé(s)</span>
            {' '}sur {nombre(bilan.analyses)} fichier(s) examiné(s) ({pourcent(bilan.mal_nommes, bilan.analyses)} %)
            {bilan.octets_mal_nommes > 0 && <span className="text-gray-500"> · {tailleLisible(bilan.octets_mal_nommes)}</span>}
          </p>
          <ul className="space-y-1.5">
            {bilan.categories.map(c => (
              <li key={c.code} className="grid grid-cols-[9rem_minmax(0,1fr)_6rem] items-center gap-2 text-sm">
                <span className="truncate">{c.libelle}{!c.actif && <span className="text-xs text-gray-400"> (règle éteinte)</span>}</span>
                <Barre pourcent={pourcent(c.mal_nommes, c.fichiers)} libelle={`${nombre(c.mal_nommes)} mal nommé(s) sur ${nombre(c.fichiers)}`} />
                <span className="text-right tabular-nums text-xs text-gray-600">{nombre(c.mal_nommes)} / {nombre(c.fichiers)}</span>
              </li>
            ))}
          </ul>
          {bilan.raisons.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-gray-600">Pourquoi</p>
              {bilan.raisons.map(r => (
                <details key={r.code} className="text-sm">
                  <summary className="cursor-pointer flex justify-between gap-2">
                    <span>{r.libelle}</span><span className="tabular-nums text-amber-700">{nombre(r.nb)}</span>
                  </summary>
                  <ul className="mt-1 ml-4 space-y-0.5">
                    {r.exemples.map(e => <li key={e} className="truncate font-mono text-xs text-gray-600" title={e}>{e}</li>)}
                    {r.nb > r.exemples.length && <li className="text-xs text-gray-400">… et {nombre(r.nb - r.exemples.length)} autre(s)</li>}
                  </ul>
                </details>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
