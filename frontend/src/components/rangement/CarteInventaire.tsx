/**
 * Rangement › Carte — où est la place : par emplacement, puis dossier par dossier.
 * Tout vient de l'inventaire (rien n'est lu sur le disque à l'affichage) : tailles et nombres de
 * fichiers calculés au scan, évolution entre les deux derniers scans, familles de types, plus gros
 * fichiers. Porté des écrans Jinja2 de rangement (`/carte`).
 */
import { useEffect, useMemo, useState } from 'react'
import { ChevronRight, Folder, FileText, HardDrive, Laptop, Loader2, Plus, Power, RefreshCw, ScanLine } from 'lucide-react'
import { clsx } from 'clsx'
import { extractApiError } from '../../api'
import { inventaireApi, planApi, type EmplacementInventaire, type PlanProposition, type VueCarte } from '../../api/inventaire'
import { useToast } from '../common/Toast'
import { confirmerTexte } from '../common/Confirmation'
import { ilYa, nombre, statutScan, tailleLisible, variation } from '../../utils/formatInventaire'
import Barre from './Barre'
import DeclarerSmb from './DeclarerSmb'

function volume(e: EmplacementInventaire): number {
  return e.dernier_scan?.statut === 'termine' ? e.dernier_scan.volume_octets : 0
}

export default function CarteInventaire() {
  const toast = useToast()
  const [emplacements, setEmplacements] = useState<EmplacementInventaire[] | null>(null)
  const [choisi, setChoisi] = useState<number | null>(null)
  const [chemin, setChemin] = useState('')
  const [vue, setVue] = useState<VueCarte | null>(null)
  const [chargement, setChargement] = useState(false)
  // « Actualiser » relit AUSSI la vue de l'emplacement (sinon un premier scan restait « Dossier vide »).
  const [relecture, setRelecture] = useState(0)
  const [nouveau, setNouveau] = useState({ libelle: '', racine: '' })
  // Racine sous laquelle déclarer (réglage du serveur) — plus de chemin écrit en dur (14/11/2026).
  const [racineAutorisee, setRacineAutorisee] = useState<string | null>(null)
  const prefixe = racineAutorisee ? `${racineAutorisee.replace(/\/+$/, '')}/` : ''
  const [ouvert, setOuvert] = useState(false)
  // Déclarer depuis une Source NAS (SMB, étape 7) ou un disque monté sur le serveur (mode historique).
  const [mode, setMode] = useState<'nas' | 'disque'>('nas')
  // Plan de classement (étape 9) : où irait chaque grand dossier, s'il a été calculé.
  const [irait, setIrait] = useState<Map<string, PlanProposition>>(new Map())

  const chargerEtat = async () => {
    try {
      const etat = await inventaireApi.etat()
      const e = etat.emplacements
      setEmplacements(e)
      setRacineAutorisee(etat.racine_autorisee ?? null)
      if (etat.racine_autorisee) setNouveau(n => (n.racine ? n : { ...n, racine: `${etat.racine_autorisee!.replace(/\/+$/, '')}/` }))
      if (choisi === null && e.length) setChoisi(e[0].id)
    } catch (err) { toast.error(extractApiError(err, "Lecture de l'inventaire impossible")) }
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void chargerEtat() }, [])

  useEffect(() => {
    if (choisi === null) return
    let annule = false
    setChargement(true)
    inventaireApi.carte(choisi, chemin)
      .then(v => { if (!annule) setVue(v) })
      .catch(err => {
        if (annule) return
        setVue(null)
        // 404 sur la racine : emplacement jamais scanné — l'encart le dit, pas une erreur.
        if (chemin) toast.error(extractApiError(err, 'Dossier introuvable dans l\'inventaire'))
      })
      .finally(() => { if (!annule) setChargement(false) })
    return () => { annule = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choisi, chemin, relecture])

  useEffect(() => {
    if (choisi === null) return
    planApi.propositions(choisi)
      .then(r => setIrait(new Map(r.propositions.map(p => [p.chemin, p]))))
      .catch(() => setIrait(new Map()))   // pas de plan pour ce partage : la colonne reste vide
  }, [choisi])

  const total = useMemo(() => (emplacements ?? []).reduce((s, e) => s + volume(e), 0), [emplacements])
  const courant = emplacements?.find(e => e.id === choisi) ?? null

  const choisir = (id: number) => { setChoisi(id); setChemin('') }

  const scanner = async (e: EmplacementInventaire) => {
    try {
      await inventaireApi.scanner(e.id)
      toast.success(`Scan de « ${e.libelle} » lancé — il se suit dans « Tâches ».`)
      await chargerEtat()
    } catch (err) { toast.error(extractApiError(err, 'Scan impossible')) }
  }

  const basculer = async (e: EmplacementInventaire) => {
    if (e.actif && !(await confirmerTexte(`Désactiver « ${e.libelle} » ? Il ne sera plus scanné ni comparé (son inventaire est gardé).`, 'Désactiver'))) return
    try { await inventaireApi.activer(e.id, !e.actif); await chargerEtat() }
    catch (err) { toast.error(extractApiError(err, 'Modification impossible')) }
  }

  const declarer = async () => {
    try {
      const r = await inventaireApi.declarer(nouveau.libelle.trim(), nouveau.racine.trim())
      toast.success(r.rescans.length
        ? `« ${r.libelle} » déclaré. Le dossier qui le contient est rescanné pour ne pas le compter deux fois.`
        : `« ${r.libelle} » déclaré. Lance son premier scan, ou attends la tournée de nuit.`)
      setNouveau({ libelle: '', racine: prefixe }); setOuvert(false)
      await chargerEtat(); setChoisi(r.id); setChemin('')
    } catch (err) {
      // Le serveur rend {code, message} pour un refus métier : on montre le message.
      const detail = (err as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail
      toast.error(detail?.message ?? extractApiError(err, 'Déclaration refusée'))
    }
  }

  if (emplacements === null) {
    return <div className="text-center text-gray-500 py-16"><Loader2 size={28} className="animate-spin mx-auto" /></div>
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[19rem_minmax(0,1fr)]">
      {/* ── Emplacements ───────────────────────────────────────────── */}
      <aside className="space-y-3 min-w-0">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Emplacements</h2>
          <button type="button" onClick={() => setOuvert(o => !o)}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50">
            <Plus size={14} /> Déclarer
          </button>
        </div>
        {ouvert && (
          <div className="flex text-xs rounded border border-gray-300 overflow-hidden" role="tablist">
            {([['nas', 'Source NAS'], ['disque', 'Disque monté']] as const).map(([m, texte]) => (
              <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
                className={clsx('flex-1 px-2 py-1', mode === m ? 'bg-blue-600 text-white' : 'bg-white hover:bg-gray-50')}>
                {texte}
              </button>
            ))}
          </div>
        )}
        {ouvert && mode === 'nas' && (
          <div className="border border-gray-200 rounded-lg p-3 bg-gray-50">
            <DeclarerSmb onAnnuler={() => setOuvert(false)}
              onDeclare={async e => { setOuvert(false); await chargerEtat(); setChoisi(e.id); setChemin('') }} />
          </div>
        )}
        {ouvert && mode === 'disque' && (
          <form className="space-y-2 border border-gray-200 rounded-lg p-3 bg-gray-50"
            onSubmit={e => { e.preventDefault(); void declarer() }}>
            <label className="block text-xs text-gray-600">Libellé
              <input value={nouveau.libelle} onChange={e => setNouveau(n => ({ ...n, libelle: e.target.value }))}
                required maxLength={100} className="mt-1 w-full px-2 py-1.5 text-sm border border-gray-300 rounded" />
            </label>
            <label className="block text-xs text-gray-600">Dossier sur le NAS
              <input value={nouveau.racine} onChange={e => setNouveau(n => ({ ...n, racine: e.target.value }))}
                required className="mt-1 w-full px-2 py-1.5 text-sm font-mono border border-gray-300 rounded" />
            </label>
            <p className="text-xs text-gray-500">
              {racineAutorisee ? <>Sous <code>{racineAutorisee}</code>. </> : null}
              L'inventaire ne fait que lire ; seul un lot que vous validez déplace des fichiers.
            </p>
            <button type="submit" className="w-full text-sm px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700">Déclarer</button>
          </form>
        )}
        {emplacements.length === 0 && (
          <p className="text-sm text-gray-500">Aucun emplacement : déclare d'abord un dossier du NAS.</p>
        )}
        <ul className="space-y-2">
          {emplacements.map(e => {
            const v = volume(e)
            const part = total ? Math.round((v * 100) / total) : 0
            const Icone = e.source === 'serveur' || e.source === 'smb' ? HardDrive : Laptop
            return (
              <li key={e.id}>
                <button type="button" onClick={() => choisir(e.id)} aria-pressed={choisi === e.id}
                  className={clsx('w-full text-left rounded-lg border p-3 hover:bg-gray-50',
                    choisi === e.id ? 'border-blue-500 ring-1 ring-blue-500' : 'border-gray-200',
                    !e.actif && 'opacity-60')}>
                  <div className="flex items-center gap-2 min-w-0">
                    <Icone size={16} className="text-gray-500 shrink-0" />
                    <span className="font-medium text-sm truncate">{e.libelle}</span>
                    {!e.actif && <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-600">désactivé</span>}
                  </div>
                  <p className="text-xs text-gray-400 font-mono truncate mt-0.5" title={e.racine}>{e.racine}</p>
                  <p className="text-sm mt-1 tabular-nums">{v ? tailleLisible(v) : '—'}</p>
                  {total > 0 && <Barre pourcent={part} libelle={`${part} % du total`} />}
                  <p className="text-xs text-gray-500 mt-1">
                    {e.source === 'serveur' ? 'NAS' : e.source === 'smb' ? 'NAS (SMB)' : e.source === 'agent' ? 'Poste (agent)' : 'Poste (import WizTree)'} ·
                    {' '}scan {statutScan(e.dernier_scan?.statut)}{e.dernier_scan?.fin ? `, ${ilYa(e.dernier_scan.fin)}` : ''}
                  </p>
                </button>
              </li>
            )
          })}
        </ul>
        {total > 0 && <p className="text-xs text-gray-500">Total inventorié : <strong>{tailleLisible(total)}</strong></p>}
      </aside>

      {/* ── Carte de l'emplacement choisi ──────────────────────────── */}
      <section className="min-w-0 space-y-4">
        {courant && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <nav aria-label="Fil d'Ariane" className="flex flex-wrap items-center gap-1 text-sm min-w-0">
              {(vue?.fil ?? [{ libelle: courant.libelle, chemin: '' }]).map((etape, i, tout) => (
                <span key={etape.chemin} className="flex items-center gap-1 min-w-0">
                  {i > 0 && <ChevronRight size={14} className="text-gray-400 shrink-0" />}
                  {i < tout.length - 1
                    ? <button type="button" onClick={() => setChemin(etape.chemin)} className="text-blue-600 hover:underline truncate">{etape.libelle}</button>
                    : <span className="font-semibold truncate">{etape.libelle}</span>}
                </span>
              ))}
            </nav>
            <div className="flex gap-2">
              {(courant.source === 'serveur' || courant.source === 'smb') && (
                <button type="button" onClick={() => void scanner(courant)} disabled={!courant.actif}
                  className="flex items-center gap-1 text-sm px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                  <ScanLine size={15} /> Scanner
                </button>
              )}
              <button type="button" onClick={() => void basculer(courant)}
                className="flex items-center gap-1 text-sm px-3 py-1.5 border border-gray-300 rounded hover:bg-gray-50">
                <Power size={15} /> {courant.actif ? 'Désactiver' : 'Réactiver'}
              </button>
              <button type="button" onClick={() => { setRelecture(n => n + 1); void chargerEtat() }} aria-label="Actualiser"
                className="px-2 py-1.5 border border-gray-300 rounded hover:bg-gray-50"><RefreshCw size={15} /></button>
            </div>
          </div>
        )}

        {courant?.dernier_scan?.statut === 'echec' && courant.dernier_scan.message && (
          <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
            Dernier scan en échec : {courant.dernier_scan.message} — rien n'a été marqué disparu.
          </p>
        )}

        {chargement && !vue && <div className="text-center py-12"><Loader2 size={24} className="animate-spin mx-auto text-gray-400" /></div>}
        {courant && !chargement && !vue && (
          <p className="text-sm text-gray-500 py-12 text-center">
            Pas encore d'inventaire pour cet emplacement : {courant.source === 'serveur' || courant.source === 'smb'
              ? 'lance un scan, ou attends la tournée de nuit.' : 'il arrive au prochain contact de son poste.'}
          </p>
        )}

        {vue && (
          <>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm bg-gray-50 border border-gray-200 rounded-lg p-3">
              <span><strong>{tailleLisible(vue.taille)}</strong></span>
              <span>{nombre(vue.nb_fichiers)} fichiers</span>
              <span>{nombre(vue.nb_dossiers)} dossiers</span>
            </div>

            <div className="overflow-x-auto border border-gray-200 rounded-lg">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs text-gray-500">
                  <tr>
                    <th className="text-left font-medium px-3 py-2">Nom</th>
                    <th className="text-left font-medium px-3 py-2 w-48">Part</th>
                    <th className="text-right font-medium px-3 py-2">Taille</th>
                    <th className="text-right font-medium px-3 py-2 hidden sm:table-cell">Fichiers</th>
                    <th className="text-right font-medium px-3 py-2 hidden md:table-cell">Évolution</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {vue.lignes.map(l => (
                    <tr key={l.chemin} className="hover:bg-gray-50">
                      <td className="px-3 py-1.5 max-w-[16rem]">
                        {l.est_dossier
                          ? <button type="button" onClick={() => setChemin(l.chemin)} className="flex items-center gap-1.5 text-blue-700 hover:underline min-w-0">
                              <Folder size={14} className="shrink-0" /><span className="truncate">{l.nom}</span></button>
                          : <span className="flex items-center gap-1.5 min-w-0"><FileText size={14} className="text-gray-400 shrink-0" /><span className="truncate">{l.nom}</span></span>}
                        {(() => {
                          const p = irait.get(l.chemin)
                          if (!p) return null
                          if (p.statut === 'en_place') return <span className="block text-[11px] text-green-700">bien placé</span>
                          if (p.statut === 'refusee') return <span className="block text-[11px] text-gray-500">laissé où il est</span>
                          if (!p.destination) return <span className="block text-[11px] text-gray-500">sans place dans le plan</span>
                          return <span className="block text-[11px] text-blue-700 truncate" title={p.raison ?? undefined}>
                            irait dans {p.destination}{p.statut === 'validee' ? ' (validé)' : ''}</span>
                        })()}
                      </td>
                      <td className="px-3 py-1.5"><Barre pourcent={l.pourcent} /></td>
                      <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">{tailleLisible(l.taille)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums hidden sm:table-cell">{l.est_dossier ? nombre(l.nb_fichiers) : ''}</td>
                      <td className={clsx('px-3 py-1.5 text-right tabular-nums whitespace-nowrap hidden md:table-cell',
                        (l.variation ?? 0) > 0 ? 'text-amber-700' : 'text-gray-500')}>{l.est_dossier ? variation(l.variation) : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {vue.reste > 0 && <p className="text-xs text-gray-500 px-3 py-2">… et {nombre(vue.reste)} élément(s) plus petits.</p>}
              {vue.lignes.length === 0 && <p className="text-sm text-gray-500 px-3 py-4">Dossier vide.</p>}
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              <div className="border border-gray-200 rounded-lg p-3 min-w-0">
                <h3 className="text-sm font-semibold mb-2">Types de fichiers</h3>
                {vue.types.length === 0 && <p className="text-xs text-gray-500">—</p>}
                <ul className="space-y-1.5">
                  {vue.types.map(t => (
                    <li key={t.famille} className="grid grid-cols-[6rem_minmax(0,1fr)_5rem] items-center gap-2 text-sm">
                      <span className="truncate">{t.famille}</span>
                      <Barre pourcent={t.pourcent} libelle={`${nombre(t.nb)} fichier(s)`} />
                      <span className="text-right tabular-nums text-xs text-gray-600">{tailleLisible(t.octets)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="border border-gray-200 rounded-lg p-3 min-w-0">
                <h3 className="text-sm font-semibold mb-2">Ce qui a grossi depuis le scan précédent</h3>
                {vue.croissances.length === 0
                  ? <p className="text-xs text-gray-500">Rien, ou pas encore deux scans à comparer.</p>
                  : <ul className="space-y-1 text-sm">
                      {vue.croissances.map(c => (
                        <li key={c.chemin} className="flex justify-between gap-2 min-w-0">
                          <span className="truncate font-mono text-xs" title={c.chemin}>{c.chemin}</span>
                          <span className="tabular-nums text-amber-700 whitespace-nowrap">{variation(c.variation)}</span>
                        </li>
                      ))}
                    </ul>}
              </div>
            </div>

            <div className="border border-gray-200 rounded-lg p-3 min-w-0">
              <h3 className="text-sm font-semibold mb-2">Les {vue.gros.length} plus gros fichiers</h3>
              <ol className="space-y-1 text-sm">
                {vue.gros.map((g, i) => (
                  <li key={g.chemin} className="flex justify-between gap-3 min-w-0">
                    <span className="truncate font-mono text-xs" title={g.chemin}><span className="text-gray-400 mr-2">{i + 1}.</span>{g.chemin}</span>
                    <span className="tabular-nums whitespace-nowrap">{tailleLisible(g.taille)}</span>
                  </li>
                ))}
              </ol>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
