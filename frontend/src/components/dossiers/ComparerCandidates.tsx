/**
 * ComparerCandidates — montrer ce qui les sépare
 * ==============================================
 * Après trois visites, les fiches se ressemblent toutes. Un mois plus tard on ne sait plus
 * laquelle disait quoi, et on choisit sur le souvenir du dernier entretien — qui n'est pas
 * le meilleur critère.
 *
 * **Aucun classement.** Ce qui décide — le courant qui passe, le lieu, le trajet réel un
 * matin de pluie — n'entre dans aucune grille, et un ordre produit par l'application serait
 * suivi précisément parce qu'il a l'air objectif. L'écran met en regard, et signale.
 *
 * **La lacune n'est pas un désaccord.** Quand l'une a répondu et l'autre pas, ce n'est pas
 * une différence entre les personnes : c'est un trou dans l'entretien. Les confondre ferait
 * écarter quelqu'un à qui on a simplement oublié de poser la question — d'où les trois
 * natures distinctes, et la lacune reléguée en dernier.
 */
import { useEffect, useState } from 'react'
import { ArrowLeft, HelpCircle, Info, Loader2, Minus, ThumbsDown, ThumbsUp } from 'lucide-react'
import { clsx } from 'clsx'
import { visitesExtrasApi, type Comparaison } from '../../api'

const AVIS: Record<string, { icone: typeof ThumbsUp; classe: string; label: string }> = {
  ok: { icone: ThumbsUp, classe: 'text-emerald-600', label: 'oui' },
  reserve: { icone: Minus, classe: 'text-amber-600', label: 'réserve' },
  non: { icone: ThumbsDown, classe: 'text-rose-600', label: 'non' },
}

const NATURES: Record<string, { label: string; classe: string; aide: string }> = {
  divergence: { label: 'opposé', classe: 'bg-rose-50 text-rose-700 border-rose-200',
    aide: 'Réponses franchement opposées — c\'est ce qui décide.' },
  nuance: { label: 'nuance', classe: 'bg-amber-50 text-amber-700 border-amber-200',
    aide: 'Un oui contre une réserve : utile, moins tranchant.' },
  lacune: { label: 'non demandé', classe: 'bg-gray-100 text-gray-500 border-gray-200',
    aide: 'La question n\'a été posée qu\'à l\'une des deux. Ce n\'est PAS un désaccord.' },
}

export default function ComparerCandidates({ slug, ids, onRetour }:
  { slug: string; ids: string[]; onRetour: () => void }) {
  const [data, setData] = useState<Comparaison | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    visitesExtrasApi.comparer(slug, ids).then(setData)
      .catch(() => setErreur('Comparaison indisponible'))
  }, [slug, ids])

  if (erreur) return <p className="text-sm text-rose-600 py-6 text-center">{erreur}</p>
  if (!data) {
    return (
      <p className="flex items-center justify-center gap-2 text-sm text-gray-400 py-10">
        <Loader2 size={15} className="animate-spin" /> Comparaison…
      </p>
    )
  }

  const nom = (p: typeof data.personnes[0]) => [p.prenom, p.nom].filter(Boolean).join(' ')

  return (
    <div className="flex flex-col gap-3">
      <button type="button" onClick={onRetour}
        className="self-start flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800">
        <ArrowLeft size={15} /> Retour à la liste
      </button>

      {/* Les repères chiffrés, mis en regard sans être notés. */}
      <section className="bg-white border border-gray-200 rounded-lg p-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left">
              <th className="pb-2 font-semibold text-gray-400 text-[10px] uppercase tracking-wide">Repère</th>
              {data.personnes.map(p => (
                <th key={p.id} className="pb-2 font-semibold text-gray-800">{nom(p)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.reperes.map(r => (
              <tr key={r.cle} className="border-t border-gray-100 align-top">
                <td className="py-1.5 pr-3">
                  <span className="text-gray-600">{r.libelle}</span>
                  <span className="block text-[10px] text-gray-400 leading-snug max-w-xs">{r.note}</span>
                </td>
                {r.valeurs.map((v, i) => (
                  <td key={i} className="py-1.5 pr-3 text-gray-800">
                    {v === null || v === '' ? <span className="text-gray-300">—</span> : String(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Les écarts, divergences en tête. */}
      {data.ecarts.length > 0 && (
        <section className="bg-white border border-gray-200 rounded-lg p-3 overflow-x-auto">
          <h4 className="text-sm font-semibold text-gray-800 mb-2">
            Ce qui les sépare <span className="font-normal text-gray-400">({data.ecarts.length})</span>
          </h4>
          <table className="w-full text-xs">
            <tbody>
              {data.ecarts.map(e => {
                const n = NATURES[e.nature]
                return (
                  <tr key={e.cle} className="border-t border-gray-100 align-top">
                    <td className="py-1.5 pr-2 w-24">
                      <span title={n.aide}
                        className={clsx('text-[10px] px-1.5 py-0.5 rounded-full border cursor-help', n.classe)}>
                        {n.label}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3">
                      <span className="text-gray-700">{e.question}</span>
                      <span className="block text-[10px] text-gray-400">{e.groupe}</span>
                    </td>
                    {e.avis.map((a, i) => {
                      const rendu = a ? AVIS[a] : null
                      const Icone = rendu?.icone ?? HelpCircle
                      return (
                        <td key={i} className="py-1.5 pr-3 whitespace-nowrap">
                          <span className={clsx('inline-flex items-center gap-1',
                            rendu?.classe ?? 'text-gray-300')}>
                            <Icone size={13} />
                            {rendu?.label ?? 'non demandé'}
                          </span>
                          {e.textes[i] && (
                            <span className="block text-[10px] text-gray-500 max-w-[14rem] leading-snug">
                              {e.textes[i]}
                            </span>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
      )}

      {data.remarques.map((r, i) => (
        <p key={i} className="flex items-start gap-1.5 text-[11px] text-gray-500 bg-gray-50
                              border border-gray-200 rounded-lg p-2 leading-relaxed">
          <Info size={13} className="shrink-0 mt-0.5 text-gray-400" />
          <span>{r.replace(/\*\*/g, '')}</span>
        </p>
      ))}
    </div>
  )
}
