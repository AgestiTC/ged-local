/**
 * CongesNaissance — simuler les congés, puis les valider dans l'agenda
 * =====================================================================
 * Ouvert depuis le planning, à côté de « Ajouter un événement ». Deux gestes, dans cet ordre,
 * et l'écran ne les confond jamais :
 *
 * - **Simuler** : on change un paramètre, les dates se recalculent. **Rien n'est écrit dans le
 *   planning.** On peut essayer un mois puis deux, fractionner puis non, sans remplir l'agenda
 *   d'hypothèses abandonnées.
 * - **Valider** : on pose un congé dans le planning — **par parent et par type**. Les décisions
 *   ne se prennent pas en même temps : le congé de maternité se déclare au 6ᵉ mois, le congé
 *   supplémentaire du co-parent se décide souvent après la naissance.
 *
 * Chaque groupe affiche son état, parce qu'un calendrier qui diverge en silence est celui
 * qu'on croit : *simulé*, *validé*, *modifié depuis* ou *devenu sans objet*.
 *
 * ## Les dates ne sont pas une promesse
 *
 * Tant que la naissance n'a pas eu lieu, tout est calculé depuis le terme et annoncé comme
 * prévisionnel. Les règles affichent leur **date de vérification** et leurs **sources** : une
 * durée de congé change (celle du congé de paternité a plus que doublé en 2021), et une date
 * fausse ici coûte un droit, pas une correction.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle, CalendarCheck, CalendarClock, Check, ExternalLink, Info, Loader2, RotateCcw, X,
} from 'lucide-react'
import { clsx } from 'clsx'
import { congesApi, type Conges, type GroupeConge, type PlanParentConges } from '../../api'
import { useToast } from '../common/Toast'

const ETATS: Record<GroupeConge['etat'], { label: string; classe: string; aide: string }> = {
  simule: { label: 'simulé', classe: 'bg-gray-100 text-gray-600 border-gray-200',
    aide: "Pas encore dans l'agenda." },
  valide: { label: 'validé', classe: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    aide: "Posé dans le planning et à jour." },
  modifie: { label: 'à revalider', classe: 'bg-amber-50 text-amber-800 border-amber-200',
    aide: "Posé dans le planning, mais les dates ont changé depuis." },
  obsolete: { label: 'à retirer', classe: 'bg-rose-50 text-rose-700 border-rose-200',
    aide: "Encore dans le planning alors qu'il ne fait plus partie du plan." },
}

const jolie = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('fr-FR')

export default function CongesNaissance({ slug, onFerme, onChange }:
  { slug: string; onFerme: () => void; onChange: () => void }) {
  const toast = useToast()
  const [data, setData] = useState<Conges | null>(null)
  const [occupe, setOccupe] = useState<string | null>(null)

  const charger = useCallback(async () => {
    try { setData(await congesApi.lire(slug)) } catch { toast.error('Congés indisponibles') }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])
  useEffect(() => { charger() }, [charger])

  /** SIMULER : n'écrit que les paramètres. Le serveur fusionne — on n'envoie que ce qui change. */
  const simuler = async (patch: Parameters<typeof congesApi.simuler>[1]) => {
    setOccupe('simulation')
    try { setData(await congesApi.simuler(slug, patch)) }
    catch { toast.error('Paramètre non enregistré') } finally { setOccupe(null) }
  }

  const valider = async (portee?: { parents?: string[]; types?: string[] }) => {
    setOccupe(JSON.stringify(portee ?? {}))
    try {
      const r = await congesApi.valider(slug, portee)
      setData(r)
      onChange()
      toast.success(r.crees || r.retires
        ? `Agenda mis à jour : ${r.crees} ajouté(s), ${r.retires} retiré(s)`
        : 'Agenda déjà à jour')
    } catch { toast.error('Validation impossible') } finally { setOccupe(null) }
  }

  const retirer = async (parent: string, type: string) => {
    setOccupe(`retirer-${parent}-${type}`)
    try { setData(await congesApi.retirer(slug, { parent, type })); onChange() }
    catch { toast.error('Retrait impossible') } finally { setOccupe(null) }
  }

  const p = data?.parametres ?? {}
  const mere = (p.mere ?? {}) as Record<string, never>
  const coparent = (p.coparent ?? {}) as Record<string, never>
  const groupe = (parent: string, type: string) =>
    data?.agenda.groupes.find(g => g.parent === parent && g.type === type)

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center p-3 overflow-y-auto"
      onClick={onFerme}>
      <div onClick={e => e.stopPropagation()}
        className="bg-white rounded-xl shadow-xl w-full max-w-5xl my-4 flex flex-col">

        <header className="flex items-center gap-2 border-b border-gray-200 p-3">
          <CalendarCheck size={17} className="text-blue-600" />
          <h2 className="text-sm font-semibold text-gray-900 flex-1">Congés de naissance</h2>
          {data?.agenda && (
            <span className={clsx('text-[11px] px-2 py-0.5 rounded-full border',
              data.agenda.a_jour ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                 : 'bg-gray-100 text-gray-500 border-gray-200')}>
              {data.agenda.a_jour ? 'agenda à jour' : 'agenda non synchronisé'}
            </span>
          )}
          <button type="button" onClick={onFerme} className="text-gray-400 hover:text-gray-700">
            <X size={17} />
          </button>
        </header>

        {!data ? (
          <p className="flex items-center gap-2 text-sm text-gray-400 p-6 justify-center">
            <Loader2 size={15} className="animate-spin" /> Chargement…
          </p>
        ) : !data.plan ? (
          <p className="flex items-start gap-2 text-sm text-amber-800 bg-amber-50 m-3 p-3 rounded-lg border border-amber-200">
            <AlertTriangle size={15} className="shrink-0 mt-0.5" /> {data.message}
          </p>
        ) : <>

          {/* Le cadre commun aux deux parents : la situation et la date réelle. */}
          <div className="p-3 flex flex-wrap items-end gap-3 border-b border-gray-100">
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Situation</span>
              <select value={String(p.situation ?? 'rang_1_2')}
                onChange={e => simuler({ situation: e.target.value })}
                className="text-sm border border-gray-300 rounded-md px-2 py-1.5 bg-white">
                {data.situations.map(s => <option key={s.cle} value={s.cle}>{s.libelle}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">
                Date réelle de naissance
              </span>
              <input type="date" defaultValue={p.naissance_reelle ?? ''}
                onBlur={e => simuler({ naissance_reelle: e.target.value || null })}
                className="text-sm border border-gray-300 rounded-md px-2 py-1.5" />
            </label>
            <p className="text-[11px] text-gray-400 flex-1 min-w-[16rem] leading-relaxed">
              Terme : <strong>{data.terme ? jolie(data.terme) : '—'}</strong>.{' '}
              {data.plan.previsionnel
                ? "Tant que la naissance n'a pas eu lieu, toutes les dates sont prévisionnelles : "
                  + 'saisissez la date réelle dès qu’elle est connue, tout sera recalculé.'
                : 'Les dates sont calculées depuis la naissance réelle.'}
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 p-3">
            {/* ── La mère ───────────────────────────────────────────────────────── */}
            <Colonne titre="Mère" plan={data.plan.mere}
              groupes={['maternite', 'csn']} groupeDe={g => groupe('mere', g)}
              occupe={occupe} onValider={t => valider({ parents: ['mere'], types: [t] })}
              onRetirer={t => retirer('mere', t)}>
              <Champ label="Report du prénatal sur le postnatal">
                <select value={String(mere.report_prenatal_semaines ?? 0)}
                  onChange={e => simuler({ mere: { report_prenatal_semaines: Number(e.target.value) } })}
                  className="text-sm border border-gray-300 rounded-md px-2 py-1 bg-white">
                  {[0, 1, 2, 3].map(n => (
                    <option key={n} value={n}>{n === 0 ? 'aucun' : `${n} semaine${n > 1 ? 's' : ''}`}</option>
                  ))}
                </select>
              </Champ>
              <ChampsCsn prefixe="mere" valeurs={mere} onChange={v => simuler({ mere: v })} />
            </Colonne>

            {/* ── Le co-parent ──────────────────────────────────────────────────── */}
            <Colonne titre="Co-parent" plan={data.plan.coparent}
              groupes={['naissance', 'paternite', 'csn']} groupeDe={g => groupe('coparent', g)}
              occupe={occupe} onValider={t => valider({ parents: ['coparent'], types: [t] })}
              onRetirer={t => retirer('coparent', t)}>
              <Champ label="Solde du congé de paternité (facultatif)">
                <label className="flex items-center gap-1.5 text-xs text-gray-600">
                  <input type="checkbox" checked={coparent.solde_pris !== false}
                    onChange={e => simuler({ coparent: { solde_pris: e.target.checked } })} />
                  je le prends
                </label>
              </Champ>
              {coparent.solde_pris !== false && <>
                <Champ label="Début du solde">
                  <input type="date" defaultValue={String(coparent.solde_debut ?? '')}
                    onBlur={e => simuler({ coparent: { solde_debut: e.target.value || null } })}
                    className="text-sm border border-gray-300 rounded-md px-2 py-1" />
                </Champ>
                <Champ label="Fractionner le solde (2 périodes de 5 jours minimum)">
                  <label className="flex items-center gap-1.5 text-xs text-gray-600">
                    <input type="checkbox" checked={Boolean(coparent.solde_fractionne)}
                      onChange={e => simuler({ coparent: { solde_fractionne: e.target.checked } })} />
                    oui
                  </label>
                </Champ>
                {Boolean(coparent.solde_fractionne) && <>
                  <Champ label="Jours de la 1ʳᵉ période">
                    <input type="number" min={5} defaultValue={String(coparent.solde_jours_1 ?? '')}
                      onBlur={e => simuler({ coparent: { solde_jours_1: Number(e.target.value) || null } })}
                      className="w-20 text-sm border border-gray-300 rounded-md px-2 py-1" />
                  </Champ>
                  <Champ label="Début de la 2ᵉ période">
                    <input type="date" defaultValue={String(coparent.solde_debut_2 ?? '')}
                      onBlur={e => simuler({ coparent: { solde_debut_2: e.target.value || null } })}
                      className="text-sm border border-gray-300 rounded-md px-2 py-1" />
                  </Champ>
                </>}
              </>}
              <ChampsCsn prefixe="coparent" valeurs={coparent}
                onChange={v => simuler({ coparent: v })} />
            </Colonne>
          </div>

          {/* Pied : tout valider, puis d'où viennent ces règles. */}
          <footer className="border-t border-gray-200 p-3 flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" disabled={occupe !== null} onClick={() => valider()}
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                {occupe === '{}' ? <Loader2 size={14} className="animate-spin" /> : <CalendarCheck size={14} />}
                Tout valider dans l'agenda
              </button>
              <button type="button" disabled={occupe !== null}
                onClick={async () => {
                  if (!confirm("Retirer du planning tous les congés posés ?\n\nCeux que vous avez "
                    + 'cochés faits sont conservés.')) return
                  setOccupe('retirer-tout')
                  try { setData(await congesApi.retirer(slug)); onChange() } finally { setOccupe(null) }
                }}
                className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                <RotateCcw size={13} /> Tout retirer
              </button>
              <span className="text-[11px] text-gray-400 ml-auto">
                Règles vérifiées le {jolie(data.regles.verifie_le)}
              </span>
            </div>
            <p className="text-[11px] text-gray-500 leading-relaxed">{data.regles.avertissement}</p>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              {data.regles.sources.map(s => (
                <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer"
                  className="flex items-center gap-1 text-[11px] text-blue-600 hover:underline">
                  {s.libelle} <ExternalLink size={10} />
                </a>
              ))}
            </div>
          </footer>
        </>}
      </div>
    </div>
  )
}


function Champ({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center justify-between gap-2 py-1 border-b border-gray-50">
      <span className="text-[11px] text-gray-500">{label}</span>
      {children}
    </label>
  )
}


/** Les mêmes quatre réglages pour les deux parents : le congé est identique pour chacun. */
function ChampsCsn({ prefixe, valeurs, onChange }:
  { prefixe: string; valeurs: Record<string, never>; onChange: (v: Record<string, unknown>) => void }) {
  const mois = Number(valeurs.csn_mois ?? 0)
  return <>
    <Champ label="Congé supplémentaire de naissance">
      <select value={String(mois)} onChange={e => onChange({ csn_mois: Number(e.target.value) })}
        className="text-sm border border-gray-300 rounded-md px-2 py-1 bg-white">
        <option value={0}>ne pas le prendre</option>
        <option value={1}>1 mois</option>
        <option value={2}>2 mois</option>
      </select>
    </Champ>
    {mois > 0 && <>
      <Champ label="Début (par défaut : à la suite)">
        <input type="date" defaultValue={String(valeurs.csn_debut ?? '')}
          key={`${prefixe}-csn-debut`}
          onBlur={e => onChange({ csn_debut: e.target.value || null })}
          className="text-sm border border-gray-300 rounded-md px-2 py-1" />
      </Champ>
      {mois === 2 && (
        <Champ label="Fractionner en 2 × 1 mois">
          <label className="flex items-center gap-1.5 text-xs text-gray-600">
            <input type="checkbox" checked={Boolean(valeurs.csn_fractionne)}
              onChange={e => onChange({ csn_fractionne: e.target.checked })} />
            oui
          </label>
        </Champ>
      )}
      {mois === 2 && Boolean(valeurs.csn_fractionne) && (
        <Champ label="Début de la 2ᵉ période">
          <input type="date" defaultValue={String(valeurs.csn_debut_2 ?? '')}
            onBlur={e => onChange({ csn_debut_2: e.target.value || null })}
            className="text-sm border border-gray-300 rounded-md px-2 py-1" />
        </Champ>
      )}
    </>}
  </>
}


function Colonne({ titre, plan, groupes, groupeDe, occupe, onValider, onRetirer, children }: {
  titre: string
  plan: PlanParentConges
  groupes: string[]
  groupeDe: (type: string) => GroupeConge | undefined
  occupe: string | null
  onValider: (type: string) => void
  onRetirer: (type: string) => void
  children: React.ReactNode
}) {
  return (
    <section className="border border-gray-200 rounded-lg flex flex-col">
      <h3 className="text-sm font-semibold text-gray-800 px-3 py-2 border-b border-gray-100 bg-gray-50/60 rounded-t-lg">
        {titre}
      </h3>

      <div className="px-3 py-1">{children}</div>

      {/* Les périodes calculées, dans l'ordre du temps. */}
      <div className="px-3 py-2 flex flex-col gap-1.5">
        {plan.periodes.map(x => (
          <div key={x.cle} className="text-xs border-l-2 border-blue-200 pl-2">
            <p className="text-gray-800">
              {x.libelle}
              {x.obligatoire && (
                <span className="ml-1 text-[10px] text-rose-700 bg-rose-50 border border-rose-200 rounded px-1">
                  obligatoire
                </span>
              )}
            </p>
            <p className="text-gray-500">
              du <strong>{jolie(x.debut)}</strong> au <strong>{jolie(x.fin)}</strong> ({x.jours} j)
              · {x.paye_par}
            </p>
            {x.note && <p className="text-[10px] text-gray-400 leading-snug">{x.note}</p>}
          </div>
        ))}
        {plan.reprise && (
          <p className="text-xs text-gray-600 border-l-2 border-emerald-300 pl-2">
            Reprise du travail : <strong>{jolie(plan.reprise)}</strong>
          </p>
        )}
      </div>

      {/* Les préavis : le seul endroit où un oubli coûte le congé lui-même. */}
      {plan.echeances.length > 0 && (
        <div className="px-3 pb-2 flex flex-col gap-1">
          {plan.echeances.map(e => (
            <p key={e.cle} className={clsx('flex items-start gap-1.5 text-[11px] leading-snug',
              e.depassee ? 'text-rose-700' : 'text-gray-500')}>
              <CalendarClock size={12} className="shrink-0 mt-0.5" />
              <span>
                <strong>{jolie(e.date)}</strong> — {e.libelle}
                {e.depassee && ' (date passée)'}
                {e.note && <span className="block text-gray-400">{e.note}</span>}
              </span>
            </p>
          ))}
        </div>
      )}

      {plan.alertes.map((a, i) => (
        <p key={i} className={clsx('mx-3 mb-2 flex items-start gap-1.5 text-[11px] rounded-md p-2 border leading-relaxed',
          a.niveau === 'bloquant' ? 'bg-rose-50 text-rose-800 border-rose-200'
            : a.niveau === 'attention' ? 'bg-amber-50 text-amber-800 border-amber-200'
            : 'bg-gray-50 text-gray-600 border-gray-200')}>
          {a.niveau === 'info' ? <Info size={12} className="shrink-0 mt-0.5" />
            : <AlertTriangle size={12} className="shrink-0 mt-0.5" />}
          {a.message}
        </p>
      ))}

      {/* Valider, type par type : les décisions ne se prennent pas en même temps. */}
      <div className="mt-auto border-t border-gray-100 p-2 flex flex-col gap-1">
        {groupes.map(type => {
          const g = groupeDe(type)
          if (!g) return null
          const etat = ETATS[g.etat]
          return (
            <div key={type} className="flex items-center gap-2">
              <span className="text-[11px] text-gray-600 flex-1 truncate" title={g.libelle}>
                {g.libelle}
              </span>
              <span title={etat.aide}
                className={clsx('text-[10px] px-1.5 py-0.5 rounded-full border cursor-help', etat.classe)}>
                {etat.label}
              </span>
              <button type="button" disabled={occupe !== null} onClick={() => onValider(type)}
                className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-blue-200 text-blue-700 hover:bg-blue-50 disabled:opacity-50">
                <Check size={11} /> {g.etat === 'simule' ? 'Valider' : 'Revalider'}
              </button>
              {g.nb_poses > 0 && (
                <button type="button" disabled={occupe !== null} onClick={() => onRetirer(type)}
                  title="Retirer du planning" className="text-gray-300 hover:text-rose-600">
                  <X size={13} />
                </button>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
