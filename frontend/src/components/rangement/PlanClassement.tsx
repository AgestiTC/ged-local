/**
 * Rangement › Plan de classement (étape 9) — « où devrait aller ce dossier ? ».
 * Conception validée : docs/conception-plan-classement.md. Rien ne bouge ici : on décide, on range à
 * l'étape 10. Trois blocs : les PROPOSITIONS (valider / corriger / refuser), l'ARBRE du plan
 * (dossiers cibles, verrouillés quand Plex en dépend), les RÈGLES (dans leur ordre de priorité).
 */
import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronRight, Lock, Loader2, Plus, RefreshCw, Sparkles, Trash2, Pencil, X, Wand2, ListChecks } from 'lucide-react'
import { clsx } from 'clsx'
import { extractApiError } from '../../api'
import { inventaireApi, planApi, type EmplacementInventaire, type PlanNoeud, type PlanProposition,
  type PlanRegle, type StatutProposition } from '../../api/inventaire'
import { useToast } from '../common/Toast'
import { confirmerTexte, saisirTexte } from '../common/Confirmation'
import { tailleLisible } from '../../utils/formatInventaire'
import LotsRangement from './LotsRangement'

const LIBELLES_STATUT: Record<StatutProposition, string> = {
  proposee: 'À décider', validee: 'Validées', refusee: 'Refusées', en_place: 'Déjà bien placés', sans_place: 'Sans place',
}
const LIBELLES_TYPE: Record<string, string> = {
  famille: 'Type de contenu', extension: 'Extension', motif_nom: 'Nom (motif)', motif_chemin: 'Chemin (motif)',
}

function partageDe(e: EmplacementInventaire): string {
  return e.racine.replace(/\/+$/, '').split('/').pop() ?? ''
}

export default function PlanClassement() {
  const toast = useToast()
  const [emplacements, setEmplacements] = useState<EmplacementInventaire[] | null>(null)
  const [choisi, setChoisi] = useState<number | null>(null)
  const [noeuds, setNoeuds] = useState<PlanNoeud[]>([])
  const [regles, setRegles] = useState<PlanRegle[]>([])
  const [props, setProps] = useState<PlanProposition[]>([])
  const [filtre, setFiltre] = useState<StatutProposition>('proposee')
  const [occupe, setOccupe] = useState(false)
  const [nouvelleRegle, setNouvelleRegle] = useState({ type: 'motif_nom', valeur: '', noeud_id: 0, priorite: 50 })

  const emp = emplacements?.find(e => e.id === choisi) ?? null
  const partage = emp ? partageDe(emp) : ''

  useEffect(() => {
    inventaireApi.etat().then(r => {
      const serveur = r.emplacements.filter(e => e.source === 'serveur' && e.actif)
      setEmplacements(serveur)
      if (serveur.length) setChoisi(serveur[0].id)
    }).catch(err => toast.error(extractApiError(err, "Lecture de l'inventaire impossible")))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const charger = async () => {
    if (!emp) return
    try {
      const [p, pr] = await Promise.all([planApi.lire(partage), planApi.propositions(emp.id)])
      setNoeuds(p.noeuds); setRegles(p.regles); setProps(pr.propositions)
    } catch (err) { toast.error(extractApiError(err, 'Lecture du plan impossible')) }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void charger() }, [choisi])

  const compte = useMemo(() => {
    const c: Record<string, number> = {}
    props.forEach(p => { c[p.statut] = (c[p.statut] ?? 0) + 1 })
    return c
  }, [props])
  const visibles = props.filter(p => p.statut === filtre)
  // Renommages d'épisodes encore ouverts, par série (`Series/<série>/S01/…`) : ils n'ont pas de règle,
  // donc pas de « Valider ses propositions » — sans ce regroupement, un clic par fichier.
  const renommagesParSerie = useMemo(() => {
    const m = new Map<string, number>()
    props.forEach(p => {
      const morceaux = p.chemin.split('/')
      if (p.nouveau_nom && p.statut === 'proposee' && morceaux.length > 2) m.set(morceaux[1], (m.get(morceaux[1]) ?? 0) + 1)
    })
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], 'fr'))
  }, [props])
  const nbRenommages = renommagesParSerie.reduce((s, [, n]) => s + n, 0)
  const validerRenommages = (serie?: string) => {
    if (!emp) return
    void action(async () => {
      const v = await planApi.validerRenommages(emp.id, serie)
      toast.success(`${v.validees} renommage(s) validé(s) — ils se rangent ci-dessous, dans « Ranger ce qui est validé ».`)
    })
  }
  const noeudsParId = useMemo(() => new Map(noeuds.map(n => [n.id, n])), [noeuds])

  const action = async (fn: () => Promise<unknown>, ok?: string) => {
    setOccupe(true)
    try { await fn(); if (ok) toast.success(ok); await charger() }
    catch (err) { toast.error(extractApiError(err, 'Action impossible')) }
    finally { setOccupe(false) }
  }

  if (emplacements === null) return <div className="text-center py-16"><Loader2 size={28} className="animate-spin mx-auto text-gray-400" /></div>
  if (emplacements.length === 0) return <p className="text-sm text-gray-500">Aucun emplacement du NAS n'est inventorié.</p>

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-gray-600">Emplacement
          <select value={choisi ?? ''} onChange={e => setChoisi(Number(e.target.value))}
            className="ml-2 px-2 py-1.5 text-sm border border-gray-300 rounded">
            {emplacements.map(e => <option key={e.id} value={e.id}>{e.libelle} — partage « {partageDe(e)} »</option>)}
          </select>
        </label>
        <p className="text-xs text-gray-500">Rien ne bouge ici : on décide où irait chaque dossier ; ranger viendra ensuite, par lots, avec annulation.</p>
      </div>

      {emp && noeuds.length === 0 && (
        <div className="border border-dashed border-gray-300 rounded-lg p-4 text-sm space-y-2">
          <p>Le partage « {partage} » n'a pas encore de plan de classement.</p>
          {partage === 'media'
            ? <button type="button" disabled={occupe} onClick={() => void action(() => planApi.chargerModele(emp.id), 'Modèle de départ chargé.')}
                className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                <Wand2 size={15} /> Charger le modèle de départ</button>
            : <p className="text-gray-500">Commence par créer ses dossiers cibles ci-dessous.</p>}
        </div>
      )}

      {/* ── Propositions ──────────────────────────────────────────── */}
      {emp && noeuds.length > 0 && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-700">Où irait chaque grand dossier</h2>
            <div className="flex gap-2">
              <button type="button" disabled={occupe}
                onClick={() => void action(() => planApi.calculer(emp.id, true), "Calcul lancé (règles, puis l'IA pour le reste) — il se suit dans « Tâches ». Actualise ensuite.")}
                className="flex items-center gap-1 text-sm px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                <Sparkles size={15} /> Calculer (règles + IA)</button>
              <button type="button" disabled={occupe}
                onClick={() => void action(() => planApi.calculer(emp.id, false), 'Calcul par les règles seules lancé — il se suit dans « Tâches ».')}
                className="text-sm px-3 py-1.5 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50">Règles seules</button>
              <button type="button" disabled={occupe}
                title="Propose de renommer les épisodes rangés en « Série - S01E01 - Titre », d'après Plex"
                onClick={() => void action(() => planApi.titres(emp.id), 'Titres des épisodes demandés à Plex — ça se suit dans « Tâches ». Actualise ensuite.')}
                className="flex items-center gap-1 text-sm px-3 py-1.5 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50">
                <Pencil size={15} /> Titres des épisodes (Plex)</button>
              <button type="button" onClick={() => void charger()} aria-label="Actualiser"
                className="px-2 py-1.5 border border-gray-300 rounded hover:bg-gray-50"><RefreshCw size={15} /></button>
            </div>
          </div>
          <div className="flex flex-wrap gap-1" role="tablist">
            {(Object.keys(LIBELLES_STATUT) as StatutProposition[]).map(s => (
              <button key={s} type="button" role="tab" aria-selected={filtre === s} onClick={() => setFiltre(s)}
                className={clsx('text-xs px-2.5 py-1 rounded-full border',
                  filtre === s ? 'bg-blue-600 text-white border-blue-600' : 'border-gray-300 text-gray-600 hover:bg-gray-50')}>
                {LIBELLES_STATUT[s]} ({compte[s] ?? 0})
              </button>
            ))}
          </div>
          {filtre === 'proposee' && nbRenommages > 0 && (
            <div className="border border-blue-200 bg-blue-50/50 rounded-lg p-3 space-y-2 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium text-gray-700">Renommages d'épisodes à décider : {nbRenommages}</p>
                <button type="button" disabled={occupe}
                  onClick={() => void (async () => {
                    if (await confirmerTexte(`Valider les ${nbRenommages} renommages d'épisodes ? Rien n'est renommé avant « Ranger ce lot », et le lot s'annule d'un clic.`, 'Tout valider'))
                      validerRenommages()
                  })()}
                  className="flex items-center gap-1 text-xs px-2 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50">
                  <ListChecks size={13} /> Tout valider</button>
              </div>
              <p className="text-xs text-gray-500">Conseil : valider une ou deux séries, ranger, vérifier dans Plex, puis le reste.</p>
              <ul className="flex flex-wrap gap-1.5">
                {renommagesParSerie.map(([serie, n]) => (
                  <li key={serie}>
                    <button type="button" disabled={occupe} onClick={() => validerRenommages(serie)}
                      title={`Valider les ${n} renommage(s) de « ${serie} »`}
                      className="flex items-center gap-1 text-xs px-2 py-0.5 border border-gray-300 bg-white rounded hover:bg-green-50 disabled:opacity-50">
                      <Check size={12} className="text-green-700" /> {serie} ({n})</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {props.length === 0 && <p className="text-sm text-gray-500">Pas encore de propositions : lance un calcul.</p>}
          {props.length > 0 && visibles.length === 0 && <p className="text-sm text-gray-500">Rien dans cette catégorie.</p>}
          <ul className="space-y-2">
            {visibles.map(p => (
              <li key={p.id} className="border border-gray-200 rounded-lg p-3 min-w-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm min-w-0">
                  <span className="font-mono text-xs truncate max-w-full" title={p.chemin}>{p.chemin}{p.contenu ? <span className="font-sans text-gray-500"> (son contenu)</span> : null}</span>
                  <ChevronRight size={14} className="text-gray-400 shrink-0" />
                  <span className="font-mono text-xs font-semibold text-blue-700 truncate">
                    {p.nouveau_nom ? `${p.nouveau_nom} (renommé sur place)` : (p.destination ?? '—')}</span>
                  <span className="text-xs text-gray-400 ml-auto whitespace-nowrap">{tailleLisible(p.taille)}</span>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  {p.par === 'regle' ? 'Par une règle' : p.par === 'ia' ? "Proposé par l'IA" : p.par === 'humain' ? 'Décidé à la main' : 'Aucune règle, pas d\'IA'}
                  {p.raison ? ` — ${p.raison}` : ''}
                  {p.par === 'ia' && p.confiance !== null ? ` (confiance ${Math.round(p.confiance * 100)}\u00a0%)` : ''}
                  {p.valide_par ? ` · décidé par ${p.valide_par}` : ''}
                </p>
                {(p.statut === 'proposee' || p.statut === 'sans_place') && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {p.destination && (
                      <button type="button" disabled={occupe} onClick={() => void action(() => planApi.decider(p.id, 'validee'))}
                        className="flex items-center gap-1 text-xs px-2 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50">
                        <Check size={13} /> Valider</button>
                    )}
                    {!p.nouveau_nom && <label className="flex items-center gap-1 text-xs">
                      <span className="text-gray-600">Plutôt vers</span>
                      <select defaultValue="" disabled={occupe} aria-label={`Corriger la destination de ${p.chemin}`}
                        onChange={e => { const v = e.target.value; if (v) void action(() => planApi.decider(p.id, 'validee', v), 'Corrigé et validé.') }}
                        className="px-1.5 py-1 border border-gray-300 rounded max-w-[14rem]">
                        <option value="">choisir…</option>
                        {noeuds.map(n => <option key={n.id} value={n.chemin}>{n.chemin}</option>)}
                      </select>
                    </label>}
                    <button type="button" disabled={occupe} onClick={() => void action(() => planApi.decider(p.id, 'refusee'))}
                      className="flex items-center gap-1 text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50">
                      <X size={13} /> Laisser où il est</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {emp && noeuds.length > 0 && <LotsRangement emplacementId={emp.id} apresChangement={() => void charger()} />}

      {emp && noeuds.length > 0 && (
        <div className="grid gap-4 xl:grid-cols-2">
          {/* ── Arbre du plan ─────────────────────────────────────── */}
          <section className="border border-gray-200 rounded-lg p-3 min-w-0">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-gray-700">Dossiers cibles du partage « {partage} »</h2>
              <button type="button" disabled={occupe}
                onClick={() => void (async () => { const nom = await saisirTexte('Nom du nouveau dossier (à la racine du partage) :'); if (nom) await action(() => planApi.creerNoeud(partage, nom, null)) })()}
                className="flex items-center gap-1 text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-50"><Plus size={13} /> Dossier</button>
            </div>
            <ul className="text-sm space-y-0.5">
              {noeuds.map(n => (
                <li key={n.id} className="flex items-center gap-1.5 group min-w-0" style={{ paddingLeft: `${(n.chemin.split('/').length - 1) * 1.1}rem` }}>
                  {n.verrouille ? <Lock size={12} className="text-amber-600 shrink-0" aria-label="verrouillé" /> : <span className="w-3 shrink-0" />}
                  <span className="truncate" title={n.description ?? n.chemin}>{n.nom}</span>
                  {n.origine === 'modele' && <span className="text-[10px] text-gray-400">modèle</span>}
                  <span className="ml-auto flex gap-1 shrink-0">
                    <button type="button" aria-label={`Ajouter un sous-dossier à ${n.nom}`} disabled={occupe}
                      onClick={() => void (async () => { const nom = await saisirTexte(`Sous-dossier de « ${n.chemin} » :`); if (nom) await action(() => planApi.creerNoeud(partage, nom, n.id)) })()}
                      className="p-1 rounded hover:bg-gray-100"><Plus size={12} /></button>
                    {!n.verrouille && (<>
                      <button type="button" aria-label={`Renommer ${n.nom}`} disabled={occupe}
                        onClick={() => void (async () => { const nom = await saisirTexte('Nouveau nom :', n.nom); if (nom && nom !== n.nom) await action(() => planApi.modifierNoeud(n.id, { nom })) })()}
                        className="p-1 rounded hover:bg-gray-100"><Pencil size={12} /></button>
                      <button type="button" aria-label={`Retirer ${n.nom} du plan`} disabled={occupe}
                        onClick={() => void (async () => { if (await confirmerTexte(`Retirer « ${n.chemin} » du plan ?`, 'Retirer')) await action(() => planApi.supprimerNoeud(n.id)) })()}
                        className="p-1 rounded hover:bg-gray-100 text-red-600"><Trash2 size={12} /></button>
                    </>)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-gray-500 mt-2"><Lock size={11} className="inline text-amber-600" /> verrouillé : un autre logiciel (Plex) dépend de son nom.</p>
          </section>

          {/* ── Règles ────────────────────────────────────────────── */}
          <section className="border border-gray-200 rounded-lg p-3 min-w-0">
            <h2 className="text-sm font-semibold text-gray-700 mb-2">Règles <span className="font-normal text-gray-500">(la plus petite priorité passe d'abord)</span></h2>
            <ul className="space-y-2">
              {regles.map(r => (
                <li key={r.id} className={clsx('text-sm border border-gray-100 rounded p-2', !r.active && 'opacity-60')}>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="text-xs tabular-nums text-gray-400">{r.priorite}</span>
                    <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100">{LIBELLES_TYPE[r.type] ?? r.type}</span>
                    <code className="text-xs">{r.valeur}</code>
                    <ChevronRight size={13} className="text-gray-400" />
                    <span className="font-mono text-xs">{noeudsParId.get(r.noeud_id)?.chemin ?? '?'}</span>
                  </div>
                  {r.description && <p className="text-xs text-gray-500 mt-0.5">{r.description}</p>}
                  <div className="flex flex-wrap gap-2 mt-1">
                    <label className="flex items-center gap-1 text-xs">
                      <input type="checkbox" checked={r.active} disabled={occupe}
                        onChange={e => void action(() => planApi.modifierRegle(r.id, { active: e.target.checked }))} /> active
                    </label>
                    {emp && (compte.proposee ?? 0) > 0 && r.active && (
                      <button type="button" disabled={occupe}
                        onClick={() => void action(async () => { const v = await planApi.validerParRegle(r.id, emp.id); toast.success(`${v.validees} proposition(s) validée(s).`) })}
                        className="flex items-center gap-1 text-xs px-2 py-0.5 border border-gray-300 rounded hover:bg-gray-50"><ListChecks size={12} /> Valider ses propositions</button>
                    )}
                    <button type="button" aria-label="Supprimer la règle" disabled={occupe}
                      onClick={() => void (async () => { if (await confirmerTexte('Supprimer cette règle ?', 'Supprimer')) await action(() => planApi.supprimerRegle(r.id)) })()}
                      className="text-xs text-red-600 hover:underline ml-auto">Supprimer</button>
                  </div>
                </li>
              ))}
            </ul>
            <form className="grid gap-2 mt-3 sm:grid-cols-2" onSubmit={e => { e.preventDefault(); void action(async () => {
              await planApi.creerRegle({ ...nouvelleRegle, noeud_id: nouvelleRegle.noeud_id || noeuds[0].id })
              setNouvelleRegle(r => ({ ...r, valeur: '' }))
            }, 'Règle ajoutée (active). Relance un calcul pour l\'appliquer.') }}>
              <select value={nouvelleRegle.type} onChange={e => setNouvelleRegle(r => ({ ...r, type: e.target.value }))}
                aria-label="Type de règle" className="px-2 py-1 text-sm border border-gray-300 rounded">
                {Object.entries(LIBELLES_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <input value={nouvelleRegle.valeur} onChange={e => setNouvelleRegle(r => ({ ...r, valeur: e.target.value }))} required
                placeholder={nouvelleRegle.type === 'extension' ? 'iso,img' : nouvelleRegle.type === 'famille' ? 'Logiciels' : '*facture*'}
                aria-label="Valeur de la règle" className="px-2 py-1 text-sm border border-gray-300 rounded" />
              <select value={nouvelleRegle.noeud_id || ''} onChange={e => setNouvelleRegle(r => ({ ...r, noeud_id: Number(e.target.value) }))}
                aria-label="Dossier cible" className="px-2 py-1 text-sm border border-gray-300 rounded">
                {noeuds.map(n => <option key={n.id} value={n.id}>{n.chemin}</option>)}
              </select>
              <div className="flex gap-2">
                <input type="number" value={nouvelleRegle.priorite} onChange={e => setNouvelleRegle(r => ({ ...r, priorite: Number(e.target.value) }))}
                  aria-label="Priorité" className="w-20 px-2 py-1 text-sm border border-gray-300 rounded" />
                <button type="submit" disabled={occupe} className="flex-1 text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">Ajouter la règle</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  )
}
