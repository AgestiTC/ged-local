/**
 * FriseConges — les congés des deux parents sur une même ligne de temps
 * =====================================================================
 * Les colonnes « Mère » et « Co-parent » disent chaque date ; elles ne disent pas **qui est à
 * la maison quand**. La frise répond à cette question-là : deux lignes alignées sur le même
 * axe, la naissance (ou le terme) en repère, et une troisième ligne pour les jours où les deux
 * parents sont en congé ensemble — c'est souvent ce que l'on cherche à arranger en réglant les
 * dates du solde de paternité ou du congé supplémentaire.
 *
 * Purement dérivée du plan calculé : rien à enregistrer, rien à valider.
 */
import { clsx } from 'clsx'
import type { PeriodeConge, PlanParentConges } from '../../api'

// Les dates sont manipulées en NUMÉROS DE JOUR (UTC) : aucun fuseau ni heure d'été ne peut
// décaler une barre d'un jour.
const JOUR = 86_400_000
const jour = (iso: string) => Math.round(Date.parse(`${iso}T00:00:00Z`) / JOUR)
const premierDuMois = (annee: number, mois: number) => Math.round(Date.UTC(annee, mois, 1) / JOUR)
const jolie = (j: number) => new Date(j * JOUR).toLocaleDateString('fr-FR', { timeZone: 'UTC' })

/** Même découpage que `_type_de` côté serveur : la clé stable dit le type de congé. */
function typeDe(cle: string): string {
  for (const t of ['maternite', 'pathologique', 'paternite', 'csn', 'naissance']) {
    if (cle === t || cle.startsWith(`${t}_`)) return t
  }
  return 'autre'
}

const COULEURS: Record<string, { barre: string; legende: string }> = {
  maternite: { barre: 'bg-pink-400', legende: 'Maternité' },
  pathologique: { barre: 'bg-amber-400', legende: 'Pathologique' },
  naissance: { barre: 'bg-sky-600', legende: 'Naissance' },
  paternite: { barre: 'bg-sky-400', legende: 'Paternité' },
  csn: { barre: 'bg-violet-400', legende: 'Supplémentaire de naissance' },
  autre: { barre: 'bg-gray-400', legende: 'Autre' },
}

type Intervalle = [number, number]   // jours, bornes incluses

/** Fusionne des intervalles qui se touchent ou se chevauchent. */
function fusion(xs: Intervalle[]): Intervalle[] {
  const out: Intervalle[] = []
  for (const [d, f] of [...xs].sort((a, b) => a[0] - b[0])) {
    const der = out[out.length - 1]
    if (der && d <= der[1] + 1) der[1] = Math.max(der[1], f)
    else out.push([d, f])
  }
  return out
}

/** Les jours où les deux parents sont en congé en même temps. */
function ensemble(a: Intervalle[], b: Intervalle[]): Intervalle[] {
  const out: Intervalle[] = []
  for (const [d1, f1] of a) for (const [d2, f2] of b) {
    const d = Math.max(d1, d2), f = Math.min(f1, f2)
    if (d <= f) out.push([d, f])
  }
  return fusion(out)
}

const intervalles = (ps: PeriodeConge[]): Intervalle[] =>
  fusion(ps.map(p => [jour(p.debut), jour(p.fin)]))

export default function FriseConges({ mere, coparent, naissance, terme }: {
  mere: PlanParentConges
  coparent: PlanParentConges
  naissance: string | null
  terme: string | null
}) {
  const toutes = [...mere.periodes, ...coparent.periodes]
  if (!toutes.length) return null

  // L'axe court du 1ᵉʳ du mois du premier congé à la fin du mois de la dernière reprise.
  const bornes = [
    ...toutes.flatMap(p => [jour(p.debut), jour(p.fin)]),
    ...[mere.reprise, coparent.reprise].filter((r): r is string => !!r).map(jour),
  ]
  const d0 = new Date(Math.min(...bornes) * JOUR)
  const d1 = new Date(Math.max(...bornes) * JOUR)
  const debut = premierDuMois(d0.getUTCFullYear(), d0.getUTCMonth())
  const fin = premierDuMois(d1.getUTCFullYear(), d1.getUTCMonth() + 1) - 1
  const total = fin - debut + 1
  const pct = (j: number) => `${((j - debut) / total) * 100}%`
  const larg = (d: number, f: number) => `${((f - d + 1) / total) * 100}%`

  const mois: { j: number; label: string }[] = []
  for (let m = d0.getUTCMonth(); ; m++) {
    const j = premierDuMois(d0.getUTCFullYear(), m)
    if (j > fin) break
    mois.push({ j, label: new Date(j * JOUR).toLocaleDateString('fr-FR',
      { month: 'short', year: '2-digit', timeZone: 'UTC' }) })
  }

  const aDeux = ensemble(intervalles(mere.periodes), intervalles(coparent.periodes))
  const joursADeux = aDeux.reduce((s, [d, f]) => s + f - d + 1, 0)

  const repere = naissance ?? terme
  const aujourdhui = Math.round(Date.now() / JOUR)
  const types = [...new Set(toutes.map(p => typeDe(p.cle)))]

  const ligne = (titre: string, plan: PlanParentConges) => (
    <div className="flex items-center gap-2">
      <span className="w-20 shrink-0 text-[11px] text-gray-600">{titre}</span>
      <div className="relative flex-1 h-6 bg-gray-50 rounded">
        {plan.periodes.map(p => {
          const d = jour(p.debut), f = jour(p.fin)
          return (
            <div key={p.cle}
              title={`${p.libelle}\ndu ${jolie(d)} au ${jolie(f)} (${p.jours} j) · ${p.paye_par}`}
              style={{ left: pct(d), width: larg(d, f), minWidth: 3 }}
              className={clsx('absolute top-1 bottom-1 rounded-sm cursor-help',
                COULEURS[typeDe(p.cle)].barre,
                p.obligatoire && 'ring-1 ring-inset ring-rose-600')} />
          )
        })}
        {plan.reprise && (
          <div title={`Reprise du travail : ${jolie(jour(plan.reprise))}`}
            style={{ left: pct(jour(plan.reprise)) }}
            className="absolute top-0 bottom-0 w-0.5 bg-emerald-500 cursor-help" />
        )}
      </div>
    </div>
  )

  return (
    <section className="mx-3 mt-3 border border-gray-200 rounded-lg p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-3">
        <h3 className="text-sm font-semibold text-gray-800">Frise des congés</h3>
        <p className="text-[11px] text-gray-500">
          {joursADeux > 0
            ? <>Les deux parents sont en congé ensemble{' '}
                <strong>{joursADeux} jour{joursADeux > 1 ? 's' : ''}</strong>.</>
            : 'Aucun jour de congé en commun.'}
        </p>
      </div>

      <div className="overflow-x-auto">
        <div className="min-w-[36rem] flex flex-col gap-1 pt-1">
          {/* Les mois. */}
          <div className="flex items-end gap-2">
            <span className="w-20 shrink-0" />
            <div className="relative flex-1 h-4">
              {mois.map(m => (
                <span key={m.j} style={{ left: pct(m.j) }}
                  className="absolute bottom-0 text-[10px] text-gray-400 pl-0.5 border-l border-gray-200 leading-none">
                  {m.label}
                </span>
              ))}
            </div>
          </div>

          <div className="relative flex flex-col gap-1 mt-2">
            {ligne('Mère', mere)}
            {ligne('Co-parent', coparent)}
            <div className="flex items-center gap-2">
              <span className="w-20 shrink-0 text-[11px] text-gray-400">Ensemble</span>
              <div className="relative flex-1 h-3">
                {aDeux.map(([d, f]) => (
                  <div key={d} title={`Ensemble du ${jolie(d)} au ${jolie(f)} (${f - d + 1} j)`}
                    style={{ left: pct(d), width: larg(d, f), minWidth: 3 }}
                    className="absolute inset-y-0.5 rounded-sm bg-emerald-300 cursor-help" />
                ))}
              </div>
            </div>

            {/* Repères verticaux sur la zone des barres : 5rem de noms + 0,5rem d'écart. */}
            <div className="pointer-events-none absolute inset-y-0 right-0 left-[5.5rem]">
              {repere && jour(repere) >= debut && jour(repere) <= fin && (
                <div style={{ left: pct(jour(repere)) }}
                  className="absolute -top-1 bottom-0 border-l-2 border-dashed border-gray-700 dark:border-slate-200">
                  <span className="absolute -top-3 left-1 text-[10px] text-gray-700 dark:text-slate-100 bg-white px-0.5 whitespace-nowrap">
                    {naissance ? 'naissance' : 'terme'}
                  </span>
                </div>
              )}
              {aujourdhui >= debut && aujourdhui <= fin && (
                <div style={{ left: pct(aujourdhui) }}
                  className="absolute top-0 bottom-0 border-l border-blue-500" />
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 text-[10px] text-gray-500">
        {types.map(t => (
          <span key={t} className="flex items-center gap-1">
            <span className={clsx('inline-block w-3 h-2 rounded-sm', COULEURS[t].barre)} />
            {COULEURS[t].legende}
          </span>
        ))}
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-2 rounded-sm ring-1 ring-inset ring-rose-600 bg-white" /> obligatoire
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-0.5 h-3 bg-emerald-500" /> reprise
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-2 rounded-sm bg-emerald-300" /> ensemble
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-0.5 h-3 bg-blue-500" /> aujourd'hui
        </span>
      </div>
    </section>
  )
}
