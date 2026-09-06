/**
 * Rétroplanning mensuel d'un dossier thématique.
 *
 * Un mois = une section ; un jalon = une carte cliquable. Le clic ouvre la fiche, où
 * vivent les options : cocher, annoter, modifier, ouvrir le lien officiel, supprimer.
 * La carte reste volontairement pauvre — titre, échéance, état — parce qu'un planning
 * de 67 entrées devient illisible dès qu'on met le détail dessus.
 *
 * `mois` est un entier SIGNÉ (négatif = grossesse). Le backend calcule les fenêtres de
 * dates depuis la date du terme ; sans elle, les mois s'affichent par leur rang.
 * Backend : /api/dossiers/{slug}/planning.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertCircle, Baby, Briefcase, CalendarDays, Check, CheckCircle2, ChevronDown, Circle,
  ClipboardList, ExternalLink, Landmark, ListChecks, Package, Pencil, Plus, Stethoscope,
  Trash2, X,
} from 'lucide-react'
import { clsx } from 'clsx'
import { dossiersApi, type Jalon, type JalonInput, type Planning } from '../../api'
import { useToast } from '../common/Toast'
import LoadingSpinner from '../common/LoadingSpinner'

/** Couleur + icône par catégorie. Une catégorie inconnue retombe sur « préparation ». */
const CAT_META: Record<string, { Icon: typeof Stethoscope; puce: string; fond: string; texte: string }> = {
  medical:       { Icon: Stethoscope,   puce: 'bg-rose-400',    fond: 'bg-rose-50',    texte: 'text-rose-700' },
  administratif: { Icon: Landmark,      puce: 'bg-blue-400',    fond: 'bg-blue-50',    texte: 'text-blue-700' },
  conges:        { Icon: Briefcase,     puce: 'bg-violet-400',  fond: 'bg-violet-50',  texte: 'text-violet-700' },
  garde:         { Icon: Baby,          puce: 'bg-emerald-400', fond: 'bg-emerald-50', texte: 'text-emerald-700' },
  materiel:      { Icon: Package,       puce: 'bg-amber-400',   fond: 'bg-amber-50',   texte: 'text-amber-700' },
  preparation:   { Icon: ClipboardList, puce: 'bg-slate-400',   fond: 'bg-slate-50',   texte: 'text-slate-700' },
  reperes:       { Icon: ListChecks,    puce: 'bg-cyan-400',    fond: 'bg-cyan-50',    texte: 'text-cyan-700' },
}
const catMeta = (c: string) => CAT_META[c] ?? CAT_META.preparation

/** « 2027-01-20 » → « 20 janv. 2027 ». Rien à installer : l'API Intl suffit. */
const jolieDate = (iso: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('fr-FR', {
    day: 'numeric', month: 'short', year: 'numeric',
  }) : null

const JALON_VIDE: JalonInput = {
  mois: 0, titre: '', detail: '', categorie: 'preparation', echeance: '', url: '', obligatoire: false,
}

// ─── Fiche d'un jalon (les « plus d'options » du clic) ───────────────────────

function FicheJalon({ jalon, mois, onFerme, onChange, onSupprime }: {
  jalon: Jalon
  mois: { libelle: string; debut: string | null; fin: string | null }
  onFerme: () => void
  onChange: (maj: Partial<JalonInput & { fait: boolean; note_perso: string | null }>) => void
  onSupprime: () => void
}) {
  const [note, setNote] = useState(jalon.note_perso ?? '')
  const [edition, setEdition] = useState(false)
  const [form, setForm] = useState<JalonInput>({
    mois: jalon.mois, titre: jalon.titre, detail: jalon.detail ?? '',
    categorie: jalon.categorie, echeance: jalon.echeance ?? '', url: jalon.url ?? '',
    sa: jalon.sa, obligatoire: jalon.obligatoire,
  })
  // La fiche peut rester ouverte pendant qu'on coche : on resynchronise la note si le
  // jalon change d'identité (navigation d'une carte à l'autre sans fermer).
  useEffect(() => { setNote(jalon.note_perso ?? '') }, [jalon.id])

  const { Icon, fond, texte } = catMeta(jalon.categorie)

  // Échap ferme la fiche — un panneau modal qui ne se ferme qu'à la souris est une impasse.
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onFerme() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onFerme])

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4"
      onClick={onFerme} role="dialog" aria-modal="true" aria-label={jalon.titre}>
      <div onClick={e => e.stopPropagation()}
        className="bg-white w-full sm:max-w-lg sm:rounded-lg rounded-t-xl shadow-xl max-h-[90vh] overflow-y-auto">

        <header className={clsx('flex items-start gap-3 px-4 py-3 border-b border-gray-100', fond)}>
          <Icon size={18} className={clsx('mt-0.5 shrink-0', texte)} />
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-gray-900 leading-snug">{jalon.titre}</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {mois.libelle}
              {mois.debut && <> · {jolieDate(mois.debut)} → {jolieDate(mois.fin)}</>}
              {jalon.sa != null && <> · {jalon.sa} SA</>}
            </p>
          </div>
          <button type="button" onClick={onFerme} aria-label="Fermer"
            className="p-1 text-gray-400 hover:text-gray-700"><X size={16} /></button>
        </header>

        <div className="p-4 space-y-4">
          {!edition ? (
            <>
              {jalon.echeance && (
                <p className={clsx('flex items-start gap-2 text-xs px-2.5 py-2 rounded-md',
                  jalon.obligatoire ? 'bg-red-50 text-red-800' : 'bg-gray-50 text-gray-600')}>
                  <AlertCircle size={13} className="mt-0.5 shrink-0" />
                  <span><strong>Échéance :</strong> {jalon.echeance}
                    {jalon.obligatoire && ' — obligatoire'}</span>
                </p>
              )}
              {jalon.detail && (
                <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-line">{jalon.detail}</p>
              )}
              {jalon.url && (
                <a href={jalon.url} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-xs text-blue-600 hover:underline">
                  <ExternalLink size={12} /> {jalon.url.replace(/^https?:\/\//, '')}
                </a>
              )}

              {/* Suivi */}
              <button type="button" onClick={() => onChange({ fait: !jalon.fait })}
                className={clsx('w-full flex items-center gap-2 px-3 py-2.5 text-sm rounded-md border transition-colors',
                  jalon.fait
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50')}>
                {jalon.fait ? <CheckCircle2 size={16} /> : <Circle size={16} />}
                {jalon.fait ? 'Fait' : 'Marquer comme fait'}
                {jalon.fait && jalon.fait_le && (
                  <span className="ml-auto text-xs text-emerald-600">
                    le {new Date(jalon.fait_le).toLocaleDateString('fr-FR')}
                  </span>
                )}
              </button>

              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Ma note</span>
                <textarea value={note} onChange={e => setNote(e.target.value)}
                  onBlur={() => note !== (jalon.note_perso ?? '') && onChange({ note_perso: note || null })}
                  rows={2} placeholder="Rendez-vous pris, document manquant, à relancer…"
                  className="mt-1 w-full px-3 py-2 text-sm border border-gray-300 rounded-md bg-white" />
              </label>

              <div className="flex items-center gap-2 pt-1">
                <button type="button" onClick={() => setEdition(true)}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-gray-600 border border-gray-200 rounded-md hover:bg-gray-50">
                  <Pencil size={12} /> Modifier
                </button>
                <button type="button" onClick={onSupprime}
                  className="ml-auto flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-50 rounded-md">
                  <Trash2 size={12} /> Retirer
                </button>
              </div>
            </>
          ) : (
            <div className="space-y-3">
              <input value={form.titre} onChange={e => setForm(f => ({ ...f, titre: e.target.value }))}
                placeholder="Titre *" className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />
              <textarea value={form.detail ?? ''} onChange={e => setForm(f => ({ ...f, detail: e.target.value }))}
                rows={4} placeholder="Le pourquoi et le comment — c'est ce qui distingue un rétroplanning d'une liste de cases."
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />
              <div className="grid grid-cols-2 gap-3">
                <select value={form.categorie} onChange={e => setForm(f => ({ ...f, categorie: e.target.value }))}
                  className="px-3 py-2 text-sm border border-gray-300 rounded-md bg-white">
                  {Object.keys(CAT_META).map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <input type="number" value={form.mois}
                  onChange={e => setForm(f => ({ ...f, mois: Number(e.target.value) }))}
                  title="Mois : négatif avant la naissance (-9 = 1ᵉʳ mois de grossesse)"
                  className="px-3 py-2 text-sm border border-gray-300 rounded-md" />
                <input value={form.echeance ?? ''} onChange={e => setForm(f => ({ ...f, echeance: e.target.value }))}
                  placeholder="Échéance (ex. avant 14 SA)"
                  className="px-3 py-2 text-sm border border-gray-300 rounded-md col-span-2" />
                <input value={form.url ?? ''} onChange={e => setForm(f => ({ ...f, url: e.target.value }))}
                  placeholder="https://…" className="px-3 py-2 text-sm border border-gray-300 rounded-md col-span-2" />
              </div>
              <label className="flex items-center gap-2 text-xs text-gray-600">
                <input type="checkbox" checked={form.obligatoire ?? false}
                  onChange={e => setForm(f => ({ ...f, obligatoire: e.target.checked }))} />
                Obligatoire ou à échéance légale
              </label>
              <div className="flex items-center gap-2">
                <button type="button" disabled={!form.titre.trim()}
                  onClick={() => { onChange(form); setEdition(false) }}
                  className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md disabled:opacity-40">
                  Enregistrer
                </button>
                <button type="button" onClick={() => setEdition(false)}
                  className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700">Annuler</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Le planning ─────────────────────────────────────────────────────────────

export default function PlanningMensuel({ slug }: { slug: string }) {
  const toast = useToast()
  const [planning, setPlanning] = useState<Planning | null>(null)
  const [loading, setLoading] = useState(true)
  const [ouvert, setOuvert] = useState<string | null>(null)      // id du jalon en fiche
  const [catFiltre, setCatFiltre] = useState<string | null>(null)
  const [resteSeul, setResteSeul] = useState(false)              // n'afficher que ce qui reste
  const [avertVisible, setAvertVisible] = useState(true)
  const [ajoutMois, setAjoutMois] = useState<number | null>(null)
  const [titreAjout, setTitreAjout] = useState('')
  const [installe, setInstalle] = useState(false)      // installation du retroplanning livre en cours

  const charger = () => {
    setLoading(true)
    dossiersApi.planning(slug)
      .then(setPlanning)
      .catch(() => toast.error('Planning indisponible'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { charger() }, [slug])

  // Mois visibles après filtres. Un mois dont tous les jalons sont masqués disparaît :
  // un titre de mois orphelin ne dit rien.
  const mois = useMemo(() => {
    if (!planning) return []
    return planning.mois
      .map(m => ({
        ...m,
        jalons: m.jalons.filter(j =>
          (!catFiltre || j.categorie === catFiltre) && (!resteSeul || !j.fait)),
      }))
      .filter(m => m.jalons.length > 0)
  }, [planning, catFiltre, resteSeul])

  const comptesParCat = useMemo(() => {
    const c: Record<string, number> = {}
    for (const m of planning?.mois ?? []) for (const j of m.jalons) c[j.categorie] = (c[j.categorie] ?? 0) + 1
    return c
  }, [planning])

  // Mois en cours : celui dont la fenêtre contient aujourd'hui. Sert au repère visuel
  // et au défilement initial — sans lui, on ouvre le planning sur le 1ᵉʳ mois de grossesse.
  const moisCourant = useMemo(() => {
    const auj = new Date().toISOString().slice(0, 10)
    return planning?.mois.find(m => m.debut && m.fin && m.debut <= auj && auj < m.fin)?.index ?? null
  }, [planning])

  const jalonOuvert = useMemo(() => {
    for (const m of planning?.mois ?? []) {
      const j = m.jalons.find(x => x.id === ouvert)
      if (j) return { jalon: j, mois: m }
    }
    return null
  }, [planning, ouvert])

  // ── Actions ────────────────────────────────────────────────────────────────
  const majJalon = async (id: string, data: Parameters<typeof dossiersApi.updateJalon>[1]) => {
    try {
      const maj = await dossiersApi.updateJalon(id, data)
      // Mise à jour locale : recharger tout le planning à chaque case cochée ferait
      // clignoter la page et perdrait la position de défilement.
      setPlanning(p => p && {
        ...p,
        stats: {
          ...p.stats,
          faits: p.mois.flatMap(m => m.jalons).filter(j => j.id === id ? maj.fait : j.fait).length,
          obligatoires_faits: p.mois.flatMap(m => m.jalons)
            .filter(j => j.obligatoire && (j.id === id ? maj.fait : j.fait)).length,
        },
        mois: p.mois.map(m => ({ ...m, jalons: m.jalons.map(j => j.id === id ? maj : j) })),
      })
    } catch { toast.error('Modification impossible') }
  }

  const supprimer = async (j: Jalon) => {
    if (!confirm(`Retirer « ${j.titre} » du planning ?`)) return
    try {
      await dossiersApi.removeJalon(j.id)
      setOuvert(null)
      toast.success('Jalon retiré')
      charger()
    } catch { toast.error('Suppression échouée') }
  }

  // Rejoue le seed du dossier : idempotent côté backend, il n'ajoute que les jalons absents
  // et ne touche jamais au suivi personnel déjà saisi.
  const installerLivre = async () => {
    setInstalle(true)
    try {
      const r = await dossiersApi.installerSeed(slug)
      toast.success(`${r.jalons_ajoutes} jalon(s) installé(s)`)
      charger()
    } catch {
      toast.error("Aucun rétroplanning n'est livré pour ce dossier")
    } finally {
      setInstalle(false)
    }
  }

  const ajouter = async (m: number) => {
    if (!titreAjout.trim()) return
    try {
      await dossiersApi.addJalon(slug, { ...JALON_VIDE, mois: m, titre: titreAjout.trim() })
      setTitreAjout(''); setAjoutMois(null)
      charger()
    } catch { toast.error('Ajout impossible') }
  }

  if (loading) return <LoadingSpinner label="Chargement du planning…" className="py-16 justify-center" />
  if (!planning) return null

  const { stats } = planning
  const pourcent = stats.total ? Math.round((stats.faits / stats.total) * 100) : 0

  return (
    <div className="space-y-5">

      {/* Ancre + avancement */}
      <section className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <CalendarDays size={16} className="text-gray-400" />
          {planning.date_terme ? (
            <p className="text-sm text-gray-700">
              Terme prévu le <strong>{jolieDate(planning.date_terme)}</strong>
            </p>
          ) : (
            <p className="text-sm text-gray-500">
              Aucune date de terme saisie — les mois s'affichent par leur rang, sans dates.
            </p>
          )}
          <Link to="/parametres?section=set-dossiers"
            className="text-xs text-blue-600 hover:underline">
            {planning.date_terme ? 'Modifier' : 'Saisir la date du terme'}
          </Link>
          <span className="ml-auto text-xs text-gray-500">
            {stats.faits} / {stats.total} fait{stats.faits > 1 ? 's' : ''}
            {stats.obligatoires > 0 && (
              <> · <span className="text-red-600">
                {stats.obligatoires_faits} / {stats.obligatoires} obligatoire{stats.obligatoires > 1 ? 's' : ''}
              </span></>
            )}
          </span>
        </div>
        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div className="h-full bg-emerald-400 transition-all" style={{ width: `${pourcent}%` }} />
        </div>

        {avertVisible && (
          <p className="flex items-start gap-2 text-xs text-amber-800 bg-amber-50 rounded-md px-2.5 py-2">
            <AlertCircle size={13} className="mt-0.5 shrink-0" />
            <span className="flex-1">{planning.avertissement}</span>
            <button type="button" onClick={() => setAvertVisible(false)}
              aria-label="Masquer l'avertissement" className="text-amber-500 hover:text-amber-700">
              <X size={13} />
            </button>
          </p>
        )}
      </section>

      {/* Filtres */}
      <div className="flex flex-wrap items-center gap-1.5">
        <button type="button" onClick={() => setCatFiltre(null)}
          className={clsx('px-2.5 py-1 text-xs rounded-full border transition-colors',
            !catFiltre ? 'border-blue-200 bg-blue-50 text-blue-800' : 'border-gray-200 text-gray-500 hover:bg-gray-50')}>
          Tout ({stats.total})
        </button>
        {Object.entries(comptesParCat).sort((a, b) => b[1] - a[1]).map(([c, n]) => {
          const { Icon } = catMeta(c)
          return (
            <button key={c} type="button" onClick={() => setCatFiltre(x => x === c ? null : c)}
              className={clsx('flex items-center gap-1 px-2.5 py-1 text-xs rounded-full border transition-colors',
                catFiltre === c ? 'border-blue-200 bg-blue-50 text-blue-800' : 'border-gray-200 text-gray-500 hover:bg-gray-50')}>
              <Icon size={12} /> {planning.categories[c] ?? c} ({n})
            </button>
          )
        })}
        <button type="button" onClick={() => setResteSeul(r => !r)}
          className={clsx('ml-auto flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-full border transition-colors',
            resteSeul ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-gray-200 text-gray-500 hover:bg-gray-50')}>
          <Check size={12} /> Reste à faire
        </button>
      </div>

      {/* Mois */}
      {mois.length === 0 && (
        stats.total === 0 ? (
          // Un dossier installé AVANT que le planning n'existe n'a pas ses jalons : le seed
          // est idempotent, mais encore faut-il savoir qu'il faut le rejouer. On le propose ici
          // plutôt que de laisser un onglet vide sans explication.
          <div className="text-center py-10 space-y-3">
            <p className="text-sm text-gray-400">Ce dossier n'a pas encore de rétroplanning.</p>
            <button type="button" onClick={installerLivre} disabled={installe}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-sm border border-blue-200 text-blue-600 rounded-lg hover:bg-blue-50 disabled:opacity-40">
              {installe ? <LoadingSpinner size={14} /> : <Plus size={14} />}
              Installer le rétroplanning livré
            </button>
          </div>
        ) : (
          <p className="text-sm text-gray-400 text-center py-10">
            {resteSeul ? 'Tout est fait sur ce périmètre.' : 'Aucun jalon ne correspond à ce filtre.'}
          </p>
        )
      )}

      {mois.map(m => {
        const faits = m.jalons.filter(j => j.fait).length
        return (
          <section key={m.index}>
            <div className={clsx('flex items-baseline gap-2 mb-2 px-2 py-1 rounded-md',
              m.index === moisCourant && 'bg-blue-50')}>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                {m.libelle}
              </h3>
              {m.debut && (
                <span className="text-xs text-gray-400">{jolieDate(m.debut)} → {jolieDate(m.fin)}</span>
              )}
              {m.index === moisCourant && (
                <span className="text-[10px] uppercase tracking-wide text-blue-700 font-semibold">
                  en cours
                </span>
              )}
              <span className="ml-auto text-xs text-gray-400">{faits}/{m.jalons.length}</span>
            </div>

            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {m.jalons.map(j => {
                const { Icon, puce } = catMeta(j.categorie)
                return (
                  <button key={j.id} type="button" onClick={() => setOuvert(j.id)}
                    className={clsx(
                      'text-left bg-white border rounded-lg p-3 transition-colors hover:border-blue-300 hover:shadow-sm',
                      j.fait ? 'border-emerald-200 bg-emerald-50/40' : 'border-gray-200')}>
                    <div className="flex items-start gap-2">
                      <span className={clsx('mt-1.5 w-1.5 h-1.5 rounded-full shrink-0', puce)} />
                      <div className="min-w-0 flex-1">
                        <p className={clsx('text-sm leading-snug',
                          j.fait ? 'text-gray-400 line-through' : 'text-gray-800')}>
                          {j.titre}
                        </p>
                        {j.echeance && (
                          <p className={clsx('text-[11px] mt-1',
                            j.obligatoire ? 'text-red-600' : 'text-gray-400')}>
                            {j.echeance}
                          </p>
                        )}
                        <div className="flex items-center gap-1.5 mt-1.5 text-gray-300">
                          <Icon size={11} />
                          {j.obligatoire && (
                            <span className="text-[10px] uppercase tracking-wide text-red-400">obligatoire</span>
                          )}
                          {j.note_perso && <Pencil size={10} className="text-blue-300" />}
                          {j.url && <ExternalLink size={10} />}
                        </div>
                      </div>
                      {j.fait
                        ? <CheckCircle2 size={15} className="text-emerald-500 shrink-0" />
                        : <ChevronDown size={14} className="text-gray-300 -rotate-90 shrink-0" />}
                    </div>
                  </button>
                )
              })}

              {/* Ajout dans ce mois */}
              {ajoutMois === m.index ? (
                <div className="border border-blue-200 rounded-lg p-2 bg-blue-50/40">
                  <input autoFocus value={titreAjout} onChange={e => setTitreAjout(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') ajouter(m.index) }}
                    placeholder="Intitulé du jalon"
                    className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md" />
                  <div className="flex gap-2 mt-2">
                    <button type="button" onClick={() => ajouter(m.index)} disabled={!titreAjout.trim()}
                      className="px-2.5 py-1 text-xs bg-blue-600 text-white rounded-md disabled:opacity-40">
                      Ajouter
                    </button>
                    <button type="button" onClick={() => { setAjoutMois(null); setTitreAjout('') }}
                      className="px-2 py-1 text-xs text-gray-500">Annuler</button>
                  </div>
                </div>
              ) : (
                <button type="button" onClick={() => { setAjoutMois(m.index); setTitreAjout('') }}
                  className="flex items-center justify-center gap-1.5 border border-dashed border-gray-200 rounded-lg p-3 text-xs text-gray-400 hover:text-blue-600 hover:border-blue-300 transition-colors">
                  <Plus size={13} /> Ajouter à ce mois
                </button>
              )}
            </div>
          </section>
        )
      })}

      {jalonOuvert && (
        <FicheJalon
          jalon={jalonOuvert.jalon}
          mois={jalonOuvert.mois}
          onFerme={() => setOuvert(null)}
          onChange={data => majJalon(jalonOuvert.jalon.id, data)}
          onSupprime={() => supprimer(jalonOuvert.jalon)}
        />
      )}
    </div>
  )
}
