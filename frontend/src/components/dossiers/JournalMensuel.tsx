/**
 * JournalMensuel — ce qui a réellement été fait, mois par mois
 * ============================================================
 * Le contrat dit ce qui est **prévu** ; ce journal dit ce qui a **eu lieu**. L'écart entre
 * les deux est la matière de deux moments de l'année :
 *
 * - **chaque mois**, remplir la déclaration Pajemploi ou CESU — heures, jours d'accueil,
 *   repas, kilomètres, exactement les cases du formulaire ;
 * - **une fois l'an**, reporter un total sur la déclaration de revenus, et solder la
 *   **régularisation** : le salaire étant lissé, on compare en décembre les heures payées
 *   aux heures faites.
 *
 * ## Un mois vide n'est pas un mois à zéro
 *
 * C'est la règle qui gouverne tout l'écran. Une case vide se lit « je n'ai pas encore
 * rempli », un 0 se lit « il n'y a rien eu ». Les confondre ferait présenter comme complète
 * une année à moitié saisie — et c'est ce total-là qu'on recopierait sur une déclaration.
 * D'où le compteur « n/12 saisis », toujours visible, et le total annoncé **partiel** tant
 * qu'il manque un mois.
 *
 * ## Aucun bulletin de salaire
 *
 * Il est édité par Pajemploi ou le CESU à partir de la déclaration, et c'est lui qui fait
 * foi. En fabriquer un ici donnerait à la salariée deux versions de sa paie. Le montant d'un
 * écart d'heures est donné au taux horaire du contrat, présenté comme une **estimation** :
 * il ignore majorations et cotisations.
 */
import { useCallback, useEffect, useState } from 'react'
import { CalendarDays, Check, Info, Loader2, Trash2 } from 'lucide-react'
import { clsx } from 'clsx'
import { journalApi, type Journal, type MoisJournal } from '../../api'
import { useToast } from '../common/Toast'

/** Les colonnes saisissables, dans l'ordre du formulaire Pajemploi. */
const COLONNES: { cle: keyof MoisJournal; titre: string; abrege: string; decimal: boolean }[] = [
  { cle: 'heures', titre: 'Heures travaillées', abrege: 'Heures', decimal: true },
  { cle: 'jours_accueil', titre: "Jours d'accueil", abrege: 'Jours', decimal: false },
  { cle: 'repas', titre: 'Repas fournis', abrege: 'Repas', decimal: false },
  { cle: 'km', titre: 'Kilomètres', abrege: 'Km', decimal: true },
  { cle: 'absences', titre: "Jours d'absence", abrege: 'Absences', decimal: false },
]

export default function JournalMensuel({ contratId }: { contratId: string }) {
  const toast = useToast()
  const [journal, setJournal] = useState<Journal | null>(null)
  const [annee, setAnnee] = useState<number | undefined>()
  const [occupe, setOccupe] = useState<string | null>(null)

  const charger = useCallback(async () => {
    try {
      const d = await journalApi.lire(contratId, annee)
      setJournal(d)
      setAnnee(a => a ?? d.annee)
    } catch { toast.error('Journal indisponible') }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contratId, annee])

  useEffect(() => { charger() }, [charger])

  /**
   * Enregistre une case. On n'envoie **que** le champ modifié : le serveur fusionne, donc
   * corriger les heures en novembre n'efface pas les repas saisis en octobre.
   */
  const saisir = async (mois: number, cle: string, brut: string | boolean) => {
    if (!journal) return
    const cellule = `${mois}-${cle}`
    setOccupe(cellule)
    try {
      // Une chaîne vide vaut « efface », pas « zéro » — c'est ainsi qu'on retire une erreur.
      const valeur = typeof brut === 'boolean' ? brut : (brut.trim() === '' ? null : brut.trim())
      setJournal(await journalApi.enregistrer(contratId, journal.annee, mois, { [cle]: valeur }))
    } catch { toast.error('Saisie non enregistrée') } finally { setOccupe(null) }
  }

  if (!journal) {
    return (
      <p className="flex items-center gap-2 text-xs text-gray-400 py-4">
        <Loader2 size={14} className="animate-spin" /> Chargement du journal…
      </p>
    )
  }

  const { totaux, remarques } = journal.recapitulatif
  const r = journal.recapitulatif
  const complet = totaux.mois_saisis === 12

  return (
    <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2.5">

      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
          <CalendarDays size={15} className="text-teal-600" /> Journal mensuel
        </h3>
        <div className="flex items-center gap-2">
          <span className={clsx('text-[11px] px-2 py-0.5 rounded-full',
            complet ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700')}>
            {totaux.mois_saisis}/12 saisis · {totaux.mois_declares} déclarés
          </span>
          <select value={journal.annee} onChange={e => setAnnee(Number(e.target.value))}
            className="text-xs border border-gray-200 rounded-md px-2 py-1 bg-white">
            {journal.annees_disponibles.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      </div>

      <p className="text-[11px] text-gray-400 leading-relaxed">
        Ce que vous reportez chaque mois sur Pajemploi ou le CESU. Une case laissée
        <strong> vide</strong> signifie « pas encore saisi » ; tapez <strong>0</strong> pour un
        mois réellement sans accueil — la différence change le total annuel.
      </p>

      <div className="overflow-x-auto -mx-1 px-1">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-gray-400">
              <th className="text-left font-semibold py-1 pr-2">Mois</th>
              {COLONNES.map(c => (
                <th key={c.cle} title={c.titre} className="text-right font-semibold py-1 px-1.5">
                  {c.abrege}
                </th>
              ))}
              <th className="text-center font-semibold py-1 px-1.5" title="Déclaré sur Pajemploi / CESU">
                Déclaré
              </th>
              <th className="w-6" />
            </tr>
          </thead>
          <tbody>
            {journal.mois.map(m => {
              const saisi = COLONNES.some(c => m[c.cle] !== null)
              return (
                <tr key={m.mois} className={clsx('border-t border-gray-100',
                  !saisi && 'text-gray-300', m.declare && 'bg-emerald-50/40')}>
                  <td className="py-0.5 pr-2 capitalize whitespace-nowrap text-gray-600">{m.nom}</td>
                  {COLONNES.map(c => (
                    <td key={c.cle} className="py-0.5 px-0.5">
                      <input type="text" inputMode={c.decimal ? 'decimal' : 'numeric'}
                        defaultValue={(m[c.cle] as string | number | null) ?? ''}
                        key={`${journal.annee}-${m.mois}-${c.cle}-${m[c.cle] ?? ''}`}
                        onBlur={e => {
                          if (e.target.value.trim() !== String(m[c.cle] ?? '')) {
                            saisir(m.mois, c.cle as string, e.target.value)
                          }
                        }}
                        disabled={occupe === `${m.mois}-${c.cle}`}
                        className="w-16 text-right text-xs border border-transparent hover:border-gray-200
                                   focus:border-blue-400 focus:bg-white rounded px-1 py-1 bg-gray-50/60
                                   disabled:opacity-40" />
                    </td>
                  ))}
                  <td className="py-0.5 px-1.5 text-center">
                    <button type="button" onClick={() => saisir(m.mois, 'declare', !m.declare)}
                      title={m.declare ? 'Déclaré — cliquer pour décocher' : 'Marquer comme déclaré'}
                      className={clsx('w-5 h-5 rounded border inline-flex items-center justify-center',
                        m.declare ? 'bg-emerald-600 border-emerald-600 text-white'
                                  : 'border-gray-300 text-transparent hover:border-emerald-400')}>
                      <Check size={12} />
                    </button>
                  </td>
                  <td className="py-0.5">
                    {saisi && (
                      <button type="button"
                        title="Vider ce mois — il redevient non saisi, pas zéro"
                        onClick={async () => {
                          setOccupe(`${m.mois}-del`)
                          try { setJournal(await journalApi.vider(contratId, journal.annee, m.mois)) }
                          finally { setOccupe(null) }
                        }}
                        className="text-gray-300 hover:text-rose-500">
                        <Trash2 size={12} />
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-gray-200 font-semibold text-gray-700">
              <td className="py-1.5 pr-2">Total {journal.annee}</td>
              <td className="py-1.5 px-1.5 text-right">{totaux.heures}</td>
              <td className="py-1.5 px-1.5 text-right">{totaux.jours_accueil}</td>
              <td className="py-1.5 px-1.5 text-right">{totaux.repas}</td>
              <td className="py-1.5 px-1.5 text-right">{totaux.km}</td>
              <td className="py-1.5 px-1.5 text-right">{totaux.absences}</td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>

      {/* La comparaison au contrat : le prévisionnel lissé face au réalisé. */}
      {r.heures_prevues && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-2.5 text-xs text-gray-600 flex flex-col gap-1">
          <p>
            Prévu au contrat : <strong>{r.heures_prevues} h</strong> sur l'année
            {r.salaire_annuel_prevu && <> · <strong>{r.salaire_annuel_prevu} €</strong> versés en douze mensualités</>}
          </p>
          {r.ecart_heures && Number(r.ecart_heures) !== 0 && (
            <p className={clsx(Number(r.ecart_heures) > 0 ? 'text-amber-800' : 'text-blue-800')}>
              Écart : <strong>{Number(r.ecart_heures) > 0 ? '+' : ''}{r.ecart_heures} h</strong>
              {r.montant_ecart && <> — soit environ <strong>{r.montant_ecart} €</strong> au taux du contrat</>}
              {!complet && <span className="text-gray-400"> (sur une année encore incomplète)</span>}
            </p>
          )}
        </div>
      )}

      {remarques.map((texte, i) => (
        <p key={i} className="flex items-start gap-1.5 text-[11px] text-amber-800 bg-amber-50
                              border border-amber-200 rounded-lg p-2 leading-relaxed">
          <Info size={13} className="shrink-0 mt-0.5" />
          <span>{texte.replace(/\*\*/g, '')}</span>
        </p>
      ))}

      <p className="text-[11px] text-gray-400 leading-relaxed">
        Matothèque n'édite <strong>aucun bulletin de salaire</strong> : il est produit par
        Pajemploi ou le CESU à partir de votre déclaration, et c'est lui qui fait foi. Les
        montants indiqués ici sont des estimations au taux du contrat, hors cotisations.
      </p>
    </section>
  )
}
