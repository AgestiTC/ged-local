/**
 * ContratExtras — ce que le contrat permet au-delà de sa rédaction
 * ================================================================
 * Quatre gestes qui prolongent le contrat, regroupés parce qu'ils partagent la même
 * question : *et maintenant ?*
 *
 * - **Le reste à charge** — « combien ça me coûte à la fin du mois ? », la question qu'on
 *   pose en premier. Aucun taux n'est inventé : chaque poste dit de quel document il sort,
 *   et un poste non renseigné n'est pas compté comme zéro.
 * - **Les annexes** — autorisations, personnes autorisées à venir chercher l'enfant, fiche
 *   de renseignements. Ce que le contrat ne règle pas et qui décide pourtant d'un mardi
 *   à 16 h.
 * - **Le dépôt en GED** — un contrat qui ne vit que dans son écran est introuvable le jour
 *   où on le cherche, des mois plus tard.
 * - **Les rappels** — déclaration mensuelle, régularisation annuelle, agrément qui expire.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle, BellRing, CheckCircle2, FileDown, FilePlus2, Info, Loader2, Paperclip,
  Wallet,
} from 'lucide-react'
import { clsx } from 'clsx'
import {
  contratExtrasApi, exportApi, type Annexe, type Contrat, type RestACharge,
} from '../../api'
import { useToast } from '../common/Toast'

export default function ContratExtras({ contrat, onChange }:
  { contrat: Contrat; onChange: () => void }) {
  const toast = useToast()
  const [cout, setCout] = useState<RestACharge | null>(null)
  const [annexes, setAnnexes] = useState<Annexe[]>([])
  const [occupe, setOccupe] = useState<string | null>(null)

  const charger = useCallback(async () => {
    try {
      const [c, a] = await Promise.all([
        contratExtrasApi.cout(contrat.id),
        contratExtrasApi.annexes(contrat.id),
      ])
      setCout(c)
      setAnnexes(a.annexes)
    } catch { /* l'écran du contrat reste utilisable sans ces compléments */ }
  }, [contrat.id])

  useEffect(() => { charger() }, [charger, contrat.champs])

  const exporter = async (cle: string, format: 'pdf' | 'docx') => {
    setOccupe(`${cle}-${format}`)
    try {
      const a = await contratExtrasApi.annexe(contrat.id, cle)
      await (format === 'pdf' ? exportApi.toPdf : exportApi.toDocx)(a.texte, a.nom_fichier)
    } catch { toast.error('Export impossible') } finally { setOccupe(null) }
  }

  return (
    <div className="flex flex-col gap-3">

      {/* ── Le reste à charge ────────────────────────────────────────────────────── */}
      <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
          <Wallet size={15} className="text-emerald-600" /> Ce qui sort vraiment chaque mois
        </h3>

        {!cout ? (
          <p className="flex items-center gap-2 text-xs text-gray-400">
            <Loader2 size={13} className="animate-spin" /> Calcul…
          </p>
        ) : <>
          <table className="w-full text-xs">
            <tbody>
              {cout.postes.map(p => (
                <tr key={p.cle} className="border-t border-gray-100">
                  <td className="py-1 pr-2">
                    <span className={clsx(!p.saisi && 'text-gray-400')}>{p.libelle}</span>
                    {/* L'origine du chiffre, toujours visible : un montant qu'on ne peut pas
                        rattacher à un document ne se vérifie pas. */}
                    <span className="block text-[10px] text-gray-400 leading-snug">{p.origine}</span>
                  </td>
                  <td className="py-1 text-right whitespace-nowrap w-24">
                    {p.montant === null ? (
                      <span className="text-amber-600 text-[11px]">non renseigné</span>
                    ) : (
                      <span className={p.sens === 'entree' ? 'text-emerald-700' : 'text-gray-800'}>
                        {p.sens === 'entree' ? '− ' : ''}{p.montant} €
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-gray-200">
                <td className="py-1.5 font-semibold text-gray-700">Reste à charge mensuel</td>
                <td className={clsx('py-1.5 text-right font-semibold text-base',
                  cout.complet ? 'text-emerald-800' : 'text-amber-700')}>
                  {cout.total} €
                </td>
              </tr>
            </tfoot>
          </table>

          {cout.remarques.map((r, i) => (
            <p key={i} className="flex items-start gap-1.5 text-[11px] text-gray-500 leading-relaxed">
              <Info size={12} className="shrink-0 mt-0.5 text-gray-300" />
              <span>{r.replace(/\*\*/g, '')}</span>
            </p>
          ))}

          <p className="text-[10px] text-gray-400">
            CMG, avance immédiate et cotisations se saisissent dans les champs du contrat
            (<strong>cmg_mensuel</strong>, <strong>avance_immediate</strong>,
            <strong> cotisations_mensuelles</strong>) — ils viennent de votre notification CAF
            et de votre relevé, que Matothèque n'a pas.
          </p>
        </>}
      </section>

      {/* ── Les annexes ──────────────────────────────────────────────────────────── */}
      {annexes.length > 0 && (
        <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
            <Paperclip size={15} className="text-amber-600" /> Annexes
          </h3>
          <p className="text-[11px] text-gray-400 leading-relaxed">
            Des documents <strong>séparés</strong>, pas des articles du contrat : une
            autorisation se retire du jour au lendemain, une clause se renégocie. Elles
            reprennent ce que le contrat sait déjà.
          </p>
          {annexes.map(a => (
            <div key={a.cle} className="flex items-start gap-2 border-t border-gray-100 pt-2">
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-gray-700">{a.titre}</p>
                <p className="text-[11px] text-gray-500 leading-relaxed">{a.resume}</p>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {(['pdf', 'docx'] as const).map(f => (
                  <button key={f} type="button" disabled={occupe === `${a.cle}-${f}`}
                    onClick={() => exporter(a.cle, f)}
                    className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                    <FileDown size={11} /> {f.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </section>
      )}

      {/* ── Dépôt en GED et rappels ──────────────────────────────────────────────── */}
      <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" disabled={!contrat.texte || occupe === 'ged'}
            title={contrat.texte
              ? "Dépose le texte relu dans la GED — il devient trouvable par la recherche"
              : "Générez d'abord le contrat"}
            onClick={async () => {
              setOccupe('ged')
              try {
                const r = await contratExtrasApi.deposer(contrat.id)
                toast.success(`Déposé dans la GED — ${r.nom}`)
                onChange()
              } catch { toast.error('Dépôt impossible') } finally { setOccupe(null) }
            }}
            className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            <FilePlus2 size={14} />
            {contrat.document_id ? 'Mettre à jour dans la GED' : 'Déposer dans la GED'}
          </button>

          {contrat.document_id && (
            <a href={`/ged?doc=${contrat.document_id}`}
              className="flex items-center gap-1 text-xs text-emerald-700 hover:underline">
              <CheckCircle2 size={13} /> voir dans la GED
            </a>
          )}

          <button type="button" disabled={occupe === 'rappels'}
            onClick={async () => {
              setOccupe('rappels')
              try {
                const r = await contratExtrasApi.rappels(contrat.id)
                toast.success(r.poses.length
                  ? `${r.poses.length} rappel(s) posé(s) au planning`
                  : `Déjà présents (${r.deja_presents})`)
              } catch { toast.error('Rappels non posés') } finally { setOccupe(null) }
            }}
            className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            <BellRing size={14} /> Poser les rappels au planning
          </button>
        </div>

        <p className="text-[11px] text-gray-400 leading-relaxed">
          Les rappels couvrent les <strong>trois prochains mois</strong> — déclaration
          mensuelle, régularisation annuelle, agrément qui expire. Revenez poser les suivants :
          un planning rempli sur cinq ans cesse d'être lu.
        </p>

        {!contrat.texte && (
          <p className="flex items-start gap-1.5 text-[11px] text-amber-700">
            <AlertTriangle size={12} className="shrink-0 mt-0.5" />
            Le dépôt en GED attend un contrat généré : c'est le texte <strong>relu</strong> qui
            est déposé, jamais une régénération.
          </p>
        )}
      </section>
    </div>
  )
}
