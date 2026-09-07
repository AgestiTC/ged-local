/**
 * Rétroplanning mensuel d'un dossier thématique.
 *
 * Deux vues sur la même matière :
 *
 * - **Cartes** : un mois = une section, un jalon = une carte. Répond à « qu'y a-t-il à
 *   faire à cette période ». Marche même sans date de terme (les mois sortent par rang).
 * - **Calendrier** : une grille mensuelle façon agenda. Répond à « qu'est-ce qui tombe
 *   ce mois-ci ». Exige la date du terme, puisque rien n'y est daté sans elle.
 *
 * Dans les deux cas, le clic ouvre la MÊME fiche, où vivent les options : cocher,
 * annoter, modifier, ouvrir le lien officiel, retirer. La carte et la pastille restent
 * pauvres — un planning de 67 entrées devient illisible dès qu'on y met le détail.
 *
 * `mois` est un entier SIGNÉ (négatif = grossesse). Le backend calcule les fenêtres de
 * dates depuis la date du terme, et date chaque jalon : au jour près quand il porte des
 * semaines d'aménorrhée, au début de sa période sinon — d'où la pastille creuse.
 *
 * **Deux natures d'entrée cohabitent, et l'écran ne doit jamais les confondre** : le
 * REPÈRE (« vers le 4ᵉ mois », posé au début de sa fenêtre, estompé) et le RENDEZ-VOUS
 * PRIS (`date_reelle` + créneau, à son jour, avec son heure). L'ajout se fait par
 * « Ajouter un événement », où une phrase en français suffit : l'IA locale en tire le
 * titre, la date et l'horaire, et REMPLIT le formulaire — la validation reste humaine.
 *
 * **Un agenda est un instantané, et il doit le dire.** La vue affiche l'âge de ses données
 * et porte un bouton pour les relire ; elle se relit aussi seule au retour sur l'onglet.
 * Un rechargement redemande TOUT ce dont l'agenda dépend — les jalons, leur suivi, et la
 * date du terme, que le backend relit en base à chaque requête.
 * Backend : /api/dossiers/{slug}/planning.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertCircle, Baby, Briefcase, CalendarClock, CalendarDays, CalendarPlus, Check, CheckCircle2, ChevronDown,
  ChevronLeft, ChevronRight, Circle, ClipboardList, Clock, ExternalLink, LayoutGrid, Landmark,
  ListChecks, Package, Download, Pencil, Plus, RefreshCw, Sparkles, Stethoscope, Trash2, X,
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
  date_reelle: '', heure_debut: '', heure_fin: '',
}

/**
 * Corps de requête à partir du formulaire.
 *
 * `mois` est RETIRÉ dès qu'une date est fixée : c'est alors au backend de le déduire du
 * terme. Retiré et non mis à `null` — un `null` explicite, sur la route de modification,
 * effacerait le mois en base au lieu de le laisser se recalculer.
 */
const corpsJalon = (f: JalonInput): JalonInput => {
  const c: JalonInput = { ...f, titre: f.titre.trim() }
  if (f.date_reelle) delete c.mois
  return c
}

/** « 13:00 » + « 14:00 » → « 13h00 → 14h00 ». Rien à afficher sans heure de début. */
const joliCreneau = (debut?: string | null, fin?: string | null) =>
  debut ? `${debut.replace(':', 'h')}${fin ? ` → ${fin.replace(':', 'h')}` : ''}` : null

// ─── Suivi des changements non exportés ──────────────────────────────────────

/**
 * Ce qui a bougé depuis le dernier export iCalendar, pour ce dossier.
 *
 * L'agenda de l'utilisateur (Google, Outlook…) est une COPIE : elle ne se met à jour que
 * s'il réimporte. Sans trace de ce qui a changé, personne ne sait quand le refaire — et un
 * planning modifié cinq fois se retrouve en décalage silencieux avec l'agenda qui sert
 * vraiment. On garde donc la liste des jalons ajoutés ou modifiés et non encore exportés.
 *
 * Deux choix assumés :
 * - on suit les **identifiants**, pas un horodatage : exporter un événement seul retire
 *   celui-là de la liste, sans prétendre que le reste est à jour ;
 * - les **suppressions** sont comptées à part, parce qu'un réimport ne les propage PAS
 *   (un fichier .ics ajoute et met à jour, il n'efface rien). Il faut le dire, pas le taire.
 *
 * Stocké dans `localStorage` : c'est une commodité d'affichage, propre à ce navigateur, et
 * son absence (navigation privée, stockage bloqué) ne doit rien casser — d'où les try/catch.
 */
type Changements = { ids: string[]; suppressions: number }
const AUCUN_CHANGEMENT: Changements = { ids: [], suppressions: 0 }

const cleChangements = (slug: string) => `matotheque:planning:${slug}:non-exportes`

function lireChangements(slug: string): Changements {
  try {
    const brut = localStorage.getItem(cleChangements(slug))
    if (!brut) return AUCUN_CHANGEMENT
    const v = JSON.parse(brut)
    return {
      ids: Array.isArray(v?.ids) ? v.ids.filter((x: unknown) => typeof x === 'string') : [],
      suppressions: Number(v?.suppressions) || 0,
    }
  } catch {
    return AUCUN_CHANGEMENT
  }
}

function ecrireChangements(slug: string, c: Changements) {
  try {
    localStorage.setItem(cleChangements(slug), JSON.stringify(c))
  } catch {
    /* stockage indisponible : le bandeau vivra le temps de la session, sans plus */
  }
}

const JOURS = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim']

/**
 * Âge des données, en clair. Dire « à l'instant » puis « il y a 12 min » vaut mieux qu'une
 * heure fixe : ce qu'on veut savoir n'est pas QUAND ça a été lu, c'est si c'est encore vrai.
 */
function fraicheur(d: Date | null): string {
  if (!d) return 'jamais chargé'
  const s = Math.floor((Date.now() - d.getTime()) / 1000)
  if (s < 30) return "à l'instant"
  if (s < 90) return 'il y a 1 min'
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`
  return `le ${d.toLocaleDateString('fr-FR')}`
}

/** Date locale → « AAAA-MM-JJ ». `toISOString()` passe par UTC et décale d'un jour le soir. */
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/**
 * Grille du mois façon calendrier : 6 semaines de 7 jours, commençant un lundi.
 * Toujours 6 lignes — une grille dont la hauteur change à chaque mois fait sauter la page.
 */
function grilleDuMois(annee: number, mois: number): Date[] {
  const premier = new Date(annee, mois, 1)
  const decalage = (premier.getDay() + 6) % 7        // getDay() : 0 = dimanche
  const debut = new Date(annee, mois, 1 - decalage)
  return Array.from({ length: 42 }, (_, i) => new Date(debut.getFullYear(), debut.getMonth(), debut.getDate() + i))
}

// ─── Vue calendrier (un mois à la fois, comme un agenda) ─────────────────────

function VueCalendrier({ planning, jalons, curseur, setCurseur, onOuvre }: {
  planning: Planning
  jalons: Jalon[]
  curseur: Date
  setCurseur: (d: Date) => void
  onOuvre: (id: string) => void
}) {
  const aujourdhui = iso(new Date())

  // Jalons indexés par jour. Les datés au jour près (déduits des SA) passent devant les
  // approximatifs : dans une case de 3 lignes, c'est le rendez-vous qui doit se voir.
  const parJour = useMemo(() => {
    const m = new Map<string, Jalon[]>()
    for (const j of jalons) {
      if (!j.date_prevue) continue
      const l = m.get(j.date_prevue) ?? []
      l.push(j)
      m.set(j.date_prevue, l)
    }
    for (const l of m.values()) l.sort((a, b) => Number(b.date_precise) - Number(a.date_precise))
    return m
  }, [jalons])

  const cases = grilleDuMois(curseur.getFullYear(), curseur.getMonth())
  const decale = (n: number) => setCurseur(new Date(curseur.getFullYear(), curseur.getMonth() + n, 1))

  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100">
        <button type="button" onClick={() => decale(-1)} aria-label="Mois précédent"
          className="p-1 text-gray-400 hover:text-gray-700"><ChevronLeft size={16} /></button>
        <span className="text-sm font-semibold text-gray-800 capitalize min-w-44 text-center">
          {curseur.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })}
        </span>
        <button type="button" onClick={() => decale(1)} aria-label="Mois suivant"
          className="p-1 text-gray-400 hover:text-gray-700"><ChevronRight size={16} /></button>
        <button type="button" onClick={() => setCurseur(new Date())}
          className="ml-auto text-xs px-2 py-1 border border-gray-200 rounded-md text-gray-500 hover:bg-gray-50">
          Aujourd'hui
        </button>
      </div>

      {/* Une semaine fait SEPT colonnes, sur téléphone comme ailleurs — on ne peut pas en
          retirer. Sur un écran de 375 px, sept colonnes tombent à ~47 px : le titre d'un jalon
          y est tronqué à deux lettres, donc illisible. On préfère un défilement horizontal, où
          les cases gardent une largeur lisible. Sur grand écran, `min-w` est inférieur au
          conteneur : rien ne change et rien ne défile. */}
      <div className="overflow-x-auto">
       <div className="min-w-[34rem]">
        <div className="grid grid-cols-7 border-b border-gray-100 bg-gray-50">
          {JOURS.map(j => (
            <div key={j} className="px-2 py-1 text-[11px] uppercase tracking-wide text-gray-400 text-center">{j}</div>
          ))}
        </div>

        <div className="grid grid-cols-7">
        {cases.map(d => {
          const cle = iso(d)
          const duMois = d.getMonth() === curseur.getMonth()
          const items = parJour.get(cle) ?? []
          return (
            <div key={cle} className={clsx(
              'min-h-24 border-b border-r border-gray-100 p-1 align-top',
              !duMois && 'bg-gray-50/60',
              cle === aujourdhui && 'bg-blue-50')}>
              <div className={clsx('text-[11px] px-1',
                cle === aujourdhui ? 'font-bold text-blue-700'
                  : duMois ? 'text-gray-500' : 'text-gray-300')}>
                {d.getDate()}
              </div>
              <div className="space-y-0.5 mt-0.5">
                {items.slice(0, 3).map(j => {
                  const { Icon, texte } = catMeta(j.categorie)
                  const creneau = joliCreneau(j.heure_debut, j.heure_fin)
                  return (
                    <button key={j.id} type="button" onClick={() => onOuvre(j.id)}
                      title={`${creneau ? `${creneau} · ` : ''}${j.titre} — ` +
                             `${planning.categories[j.categorie] ?? j.categorie}` +
                             (j.date_precise ? '' : ' (période, pas un rendez-vous)')}
                      className={clsx(
                        'w-full flex items-center gap-1 px-1 py-0.5 rounded text-[10px] text-left transition-colors hover:bg-gray-100',
                        j.fait && 'opacity-40 line-through')}>
                      {/* L'ICÔNE de la catégorie, dans SA couleur : la même que celle du filtre
                          correspondant. Un jalon sans SA n'a pas de date réelle → estompé, pour
                          ne pas faire croire à un rendez-vous là où il n'y a qu'une période. */}
                      <Icon size={10} className={clsx('shrink-0', texte, !j.date_precise && 'opacity-40')} />
                      {/* L'heure d'abord : dans une case de calendrier, c'est elle qu'on
                          cherche. Elle n'apparaît que sur un rendez-vous réellement pris. */}
                      {j.heure_debut && (
                        <span className="shrink-0 font-semibold text-gray-500 tabular-nums">
                          {j.heure_debut.replace(':', 'h')}
                        </span>
                      )}
                      <span className="truncate text-gray-700">{j.titre}</span>
                    </button>
                  )
                })}
                {items.length > 3 && (
                  <button type="button" onClick={() => onOuvre(items[3].id)}
                    className="w-full px-1 text-[10px] text-left text-gray-400 hover:text-gray-600">
                    +{items.length - 3} autre{items.length - 3 > 1 ? 's' : ''}
                  </button>
                )}
              </div>
            </div>
          )
        })}
        </div>
       </div>
      </div>

      <p className="px-3 py-2 text-[11px] text-gray-400 border-t border-gray-100">
        L'icône reprend la couleur de sa catégorie, celle des filtres ci-dessus. Icône pleine =
        date au jour près — rendez-vous saisi, ou déduite des semaines d'aménorrhée (terme =
        41 SA) ; icône estompée = jalon sans date propre, posé au début de sa période. Une
        heure affichée signale un créneau réellement pris.
        {planning.date_terme && <> Terme : {jolieDate(planning.date_terme)}.</>}
      </p>
    </div>
  )
}

// ─── Champs d'un événement (partagés : ajout et modification) ────────────────

const CHAMP = 'mt-1 w-full px-3 py-2 text-sm border border-gray-300 rounded-md bg-white disabled:bg-gray-50 disabled:text-gray-400'
const LEGENDE = 'text-xs font-semibold uppercase tracking-wide text-gray-400'

/**
 * Les champs d'un événement, en un seul endroit : l'ajout et la modification montrent
 * exactement le même formulaire.
 *
 * Deux régimes de temps s'y excluent, et c'est voulu :
 *
 * - une **date** (rendez-vous pris) → le mois se déduit, on ne le demande pas ;
 * - pas de date → le **mois** situe la période, et rien ne prétend à un horaire.
 *
 * Demander les deux ferait saisir à la main un calcul que le serveur sait faire, et
 * laisserait créer un jalon qui se dit à la fois « le 25 septembre » et « au 4ᵉ mois ».
 */
function ChampsEvenement({ form, setForm, categories }: {
  form: JalonInput
  setForm: (maj: (p: JalonInput) => JalonInput) => void
  categories: Record<string, string>
}) {
  const date = form.date_reelle ?? ''
  const maj = (p: Partial<JalonInput>) => setForm(f => ({ ...f, ...p }))

  return (
    <div className="space-y-3">
      <input autoFocus value={form.titre} onChange={e => maj({ titre: e.target.value })}
        placeholder="Titre *" aria-label="Titre de l'événement"
        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <label className="block col-span-2">
          <span className={LEGENDE}>Date</span>
          <input type="date" value={date} onChange={e => maj({ date_reelle: e.target.value })}
            className={CHAMP} />
        </label>
        {/* Les horaires n'existent qu'avec une date : une heure sur un événement qui n'est
            posé que « quelque part dans le mois » ferait croire à un créneau réservé. */}
        <label className="block">
          <span className={LEGENDE}>Début</span>
          <input type="time" value={form.heure_debut ?? ''} disabled={!date}
            onChange={e => maj({ heure_debut: e.target.value })} className={CHAMP} />
        </label>
        <label className="block">
          <span className={LEGENDE}>Fin</span>
          <input type="time" value={form.heure_fin ?? ''} disabled={!date || !form.heure_debut}
            onChange={e => maj({ heure_fin: e.target.value })} className={CHAMP} />
        </label>
      </div>

      <p className="text-[11px] text-gray-400">
        {date
          ? 'Rendez-vous daté : il tombe à ce jour dans le calendrier, et se range tout seul dans le mois correspondant.'
          : "Sans date, l'événement marque une période : il se pose au début de son mois, en estompé."}
      </p>

      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className={LEGENDE}>Catégorie</span>
          <select value={form.categorie} onChange={e => maj({ categorie: e.target.value })}
            className={CHAMP}>
            {Object.keys(CAT_META).map(c => <option key={c} value={c}>{categories[c] ?? c}</option>)}
          </select>
        </label>
        {!date && (
          <label className="block">
            <span className={LEGENDE}>Mois du planning</span>
            <input type="number" value={form.mois ?? 0}
              onChange={e => maj({ mois: Number(e.target.value) })}
              title="Négatif avant la naissance : -9 = 1ᵉʳ mois de grossesse, 0 = naissance"
              className={CHAMP} />
          </label>
        )}
      </div>

      <textarea value={form.detail ?? ''} onChange={e => maj({ detail: e.target.value })}
        rows={3} placeholder="Détail — le pourquoi et le comment, ce qui distingue un planning d'une liste de cases."
        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />
      <input value={form.echeance ?? ''} onChange={e => maj({ echeance: e.target.value })}
        placeholder="Échéance réglementaire (ex. avant 14 SA)"
        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />
      <input value={form.url ?? ''} onChange={e => maj({ url: e.target.value })}
        placeholder="https://…" className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md" />
      <label className="flex items-center gap-2 text-xs text-gray-600">
        <input type="checkbox" checked={form.obligatoire ?? false}
          onChange={e => maj({ obligatoire: e.target.checked })} />
        Obligatoire ou à échéance légale
      </label>
    </div>
  )
}

/**
 * Saisie assistée par l'IA LOCALE : une phrase en français — « entretien prénatal à la
 * maternité le 25 septembre de 13h à 14h » — et le formulaire se remplit.
 *
 * Elle REMPLIT, elle n'enregistre pas. Le modèle se trompe de jour de temps en temps, et
 * un rendez-vous faux dans un agenda est pire qu'un rendez-vous absent : la proposition
 * passe donc toujours sous les yeux de l'utilisateur avant d'être écrite. Le texte source
 * reste affiché après coup — c'est le témoin qui permet de vérifier ce qui a été compris.
 */
function ZoneIA({ slug, texte, setTexte, onProposition }: {
  slug: string
  texte: string
  setTexte: (t: string) => void
  onProposition: (p: Partial<JalonInput>) => void
}) {
  const toast = useToast()
  const [encours, setEncours] = useState(false)

  const analyser = async () => {
    if (!texte.trim() || encours) return
    setEncours(true)
    try {
      const p = await dossiersApi.analyserJalon(slug, texte.trim())
      onProposition({
        titre: p.titre,
        detail: p.detail ?? '',
        categorie: p.categorie,
        date_reelle: p.date_reelle ?? '',
        heure_debut: p.heure_debut ?? '',
        heure_fin: p.heure_fin ?? '',
        obligatoire: p.obligatoire,
      })
      toast.success(p.date_reelle
        ? 'Proposition remplie — relisez la date et l’heure'
        : "Proposition remplie — aucune date reconnue dans le texte")
    } catch {
      toast.error('Analyse impossible (IA locale injoignable ?)')
    } finally {
      setEncours(false)
    }
  }

  return (
    <div className="rounded-lg border border-violet-200 bg-violet-50/50 p-3 space-y-2">
      <p className="flex items-center gap-1.5 text-xs font-semibold text-violet-800">
        <Sparkles size={13} /> Décrire l'événement en une phrase
      </p>
      <textarea value={texte} onChange={e => setTexte(e.target.value)} rows={2}
        placeholder="Entretien prénatal à la maternité le vendredi 25 septembre de 13h à 14h"
        className="w-full px-3 py-2 text-sm border border-violet-200 rounded-md bg-white" />
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={analyser} disabled={!texte.trim() || encours}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-white bg-violet-600 rounded-md hover:bg-violet-700 disabled:opacity-40">
          {encours ? <LoadingSpinner size={12} /> : <Sparkles size={12} />}
          {encours ? 'Analyse…' : 'Remplir avec l’IA'}
        </button>
        <span className="text-[11px] text-violet-700/80">
          IA locale (Ollama) — elle remplit le formulaire, rien n'est enregistré sans vous.
        </span>
      </div>
    </div>
  )
}

/**
 * Modale d'ajout : la phrase à l'IA en haut, le formulaire dessous, dans le même écran.
 *
 * Une fois l'événement enregistré, elle ne se ferme PAS : elle propose de l'exporter vers
 * l'agenda que l'utilisateur consulte vraiment (Google, Outlook, Apple). C'est le moment où
 * l'information est fraîche et où le geste a du sens — le proposer plus tard revient à ne
 * pas le proposer. L'export reste un fichier téléchargé : rien ne part vers un tiers.
 */
function ModaleEvenement({ slug, moisInitial, categories, onFerme, onAjoute, onExporte }: {
  slug: string
  moisInitial: number
  categories: Record<string, string>
  onFerme: () => void
  onAjoute: (j: Jalon) => void
  onExporte: (id: string) => void
}) {
  const toast = useToast()
  const [form, setForm] = useState<JalonInput>({ ...JALON_VIDE, mois: moisInitial })
  const [texte, setTexte] = useState('')
  const [enregistre, setEnregistre] = useState(false)
  const [cree, setCree] = useState<Jalon | null>(null)   // événement enregistré → écran d'export

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onFerme() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onFerme])

  const soumettre = async () => {
    if (!form.titre.trim() || enregistre) return
    setEnregistre(true)
    try {
      const j = await dossiersApi.addJalon(slug, corpsJalon(form))
      toast.success('Événement ajouté au planning')
      setCree(j)
      onAjoute(j)
    } catch {
      toast.error('Ajout impossible')
    } finally {
      setEnregistre(false)
    }
  }

  const encoreUn = () => {
    setCree(null)
    setForm({ ...JALON_VIDE, mois: moisInitial })
    setTexte('')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4"
      onClick={onFerme} role="dialog" aria-modal="true" aria-label="Nouvel événement">
      <div onClick={e => e.stopPropagation()}
        className="bg-white w-full sm:max-w-lg sm:rounded-lg rounded-t-xl shadow-xl max-h-[90vh] overflow-y-auto">
        <header className="flex items-center gap-3 px-4 py-3 border-b border-gray-100">
          <CalendarPlus size={18} className="text-blue-600 shrink-0" />
          <h3 className="text-sm font-semibold text-gray-900 flex-1">
            {cree ? 'Événement ajouté' : 'Nouvel événement'}
          </h3>
          <button type="button" onClick={onFerme} aria-label="Fermer"
            className="p-1 text-gray-400 hover:text-gray-700"><X size={16} /></button>
        </header>

        {!cree ? (<>
          <div className="p-4 space-y-4">
            <ZoneIA slug={slug} texte={texte} setTexte={setTexte}
              onProposition={p => setForm(f => ({ ...f, ...p }))} />
            <ChampsEvenement form={form} setForm={setForm} categories={categories} />
          </div>

          <footer className="flex items-center gap-2 px-4 py-3 border-t border-gray-100 sticky bottom-0 bg-white">
            <button type="button" onClick={soumettre} disabled={!form.titre.trim() || enregistre}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md disabled:opacity-40">
              {enregistre ? 'Enregistrement…' : 'Ajouter au planning'}
            </button>
            <button type="button" onClick={onFerme}
              className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700">Annuler</button>
          </footer>
        </>) : (
          <div className="p-4 space-y-4">
            <p className="flex items-start gap-2 text-sm text-emerald-800 bg-emerald-50 rounded-md px-3 py-2">
              <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
              <span>
                <strong>{cree.titre}</strong> est dans le planning
                {cree.date_reelle && <> — {jolieDate(cree.date_reelle)}
                  {cree.heure_debut && <> à {joliCreneau(cree.heure_debut, cree.heure_fin)}</>}</>}.
              </span>
            </p>

            <ExportEvenement jalon={cree} onExporte={onExporte} />

            <div className="flex items-center gap-2 pt-1">
              <button type="button" onClick={encoreUn}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm text-blue-600 border border-blue-200 rounded-md hover:bg-blue-50">
                <Plus size={14} /> Ajouter un autre
              </button>
              <button type="button" onClick={onFerme}
                className="ml-auto px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700">Fermer</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Proposition d'export d'UN événement vers un agenda extérieur.
 *
 * Un **vrai lien** `<a download>`, jamais un téléchargement piloté en JavaScript : c'est la
 * seule voie fiable quand l'application est servie en HTTP (cf. CLAUDE.md, contexte non
 * sécurisé). Et un événement sans date n'a rien à poser dans un agenda — on le dit plutôt
 * que d'offrir un bouton qui rendrait une erreur.
 */
function ExportEvenement({ jalon, onExporte }: {
  jalon: Jalon
  onExporte: (id: string) => void
}) {
  if (!jalon.date_prevue) {
    return (
      <p className="text-xs text-gray-500 bg-gray-50 rounded-md px-3 py-2">
        Cet événement n'a pas encore de date — ni date propre, ni date de terme pour la
        calculer. Il n'y a donc rien à poser dans un agenda extérieur pour l'instant.
      </p>
    )
  }
  return (
    <div className="space-y-2">
      <p className="text-sm text-gray-600">
        Pour le retrouver dans votre agenda habituel (Google, Outlook, Apple…) : téléchargez
        le fichier <code className="text-xs bg-gray-100 px-1 rounded">.ics</code> et importez-le.
        Rien n'est envoyé à un service extérieur — c'est vous qui déposez le fichier.
      </p>
      <a href={dossiersApi.jalonIcsUrl(jalon.id)} download onClick={() => onExporte(jalon.id)}
        className="inline-flex items-center gap-1.5 px-3 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700">
        <Download size={14} /> Exporter cet événement (.ics)
      </a>
      <p className="text-[11px] text-gray-400">
        Réimporter le même événement le <strong>met à jour</strong> au lieu de le dupliquer.
      </p>
    </div>
  )
}

// ─── Fiche d'un jalon (les « plus d'options » du clic) ───────────────────────

function FicheJalon({ jalon, mois, slug, categories, onFerme, onChange, onSupprime }: {
  jalon: Jalon
  mois: { libelle: string; debut: string | null; fin: string | null }
  slug: string
  categories: Record<string, string>
  onFerme: () => void
  onChange: (maj: Partial<JalonInput & { fait: boolean; note_perso: string | null }>) => void
  onSupprime: () => void
}) {
  const toast = useToast()
  const [note, setNote] = useState(jalon.note_perso ?? '')
  const [edition, setEdition] = useState(false)
  const [datation, setDatation] = useState(false)
  const formDepuis = (j: Jalon): JalonInput => ({
    mois: j.mois, titre: j.titre, detail: j.detail ?? '',
    categorie: j.categorie, echeance: j.echeance ?? '', url: j.url ?? '',
    sa: j.sa, obligatoire: j.obligatoire,
    date_reelle: j.date_reelle ?? '', heure_debut: j.heure_debut ?? '', heure_fin: j.heure_fin ?? '',
  })
  const [form, setForm] = useState<JalonInput>(() => formDepuis(jalon))
  // La fiche peut rester ouverte pendant qu'on coche : on resynchronise la note si le
  // jalon change d'identité (navigation d'une carte à l'autre sans fermer).
  useEffect(() => { setNote(jalon.note_perso ?? ''); setForm(formDepuis(jalon)); setEdition(false) },
    [jalon.id])

  /**
   * « Rendez-vous pris le vendredi 25 septembre de 13h à 14h » écrit dans la note → une
   * date et un créneau sur CE jalon.
   *
   * On ne reprend de la proposition que la **date et les heures** : le titre du jalon
   * existe déjà et vaut mieux que celui qu'on tirerait d'une note prise à la volée. Et on
   * bascule en modification plutôt que d'enregistrer — c'est l'utilisateur qui confirme.
   */
  const daterDepuisLaNote = async () => {
    const texte = note.trim()
    if (!texte || datation) return
    setDatation(true)
    try {
      const p = await dossiersApi.analyserJalon(slug, texte)
      if (!p.date_reelle) {
        toast.error("Aucune date reconnue dans la note")
        return
      }
      setForm(f => ({
        ...f,
        date_reelle: p.date_reelle ?? '',
        heure_debut: p.heure_debut ?? '',
        heure_fin: p.heure_fin ?? '',
      }))
      setEdition(true)
      toast.success('Date proposée — vérifiez, puis enregistrez')
    } catch {
      toast.error('Analyse impossible (IA locale injoignable ?)')
    } finally {
      setDatation(false)
    }
  }

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
            {/* Un rendez-vous PRIS affiche sa date et son heure d'abord : c'est
                l'information qu'on vient chercher. La fenêtre du mois passe derrière. */}
            <p className="text-xs text-gray-500 mt-0.5">
              {jalon.date_reelle ? (
                <>
                  <span className="font-semibold text-gray-700">{jolieDate(jalon.date_reelle)}</span>
                  {jalon.heure_debut && <> · {joliCreneau(jalon.heure_debut, jalon.heure_fin)}</>}
                  {' · '}{mois.libelle}
                </>
              ) : (
                <>
                  {mois.libelle}
                  {mois.debut && <> · {jolieDate(mois.debut)} → {jolieDate(mois.fin)}</>}
                </>
              )}
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
                <span className={LEGENDE}>Ma note</span>
                <textarea value={note} onChange={e => setNote(e.target.value)}
                  onBlur={() => note !== (jalon.note_perso ?? '') && onChange({ note_perso: note || null })}
                  rows={2} placeholder="Rendez-vous pris, document manquant, à relancer…"
                  className="mt-1 w-full px-3 py-2 text-sm border border-gray-300 rounded-md bg-white" />
              </label>

              {/* Une note dit souvent « rendez-vous pris le 25 septembre à 13h » — et cette
                  date reste alors enfermée dans du texte, invisible dans le calendrier.
                  Ce bouton l'en sort, sans rien enregistrer : il ouvre la modification
                  avec la date proposée, à confirmer. */}
              {note.trim() && (
                <button type="button" onClick={daterDepuisLaNote} disabled={datation}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-violet-700 border border-violet-200 bg-violet-50/60 rounded-md hover:bg-violet-100 disabled:opacity-40">
                  {datation ? <LoadingSpinner size={12} /> : <Sparkles size={12} />}
                  {datation ? 'Analyse…' : 'Dater depuis ma note (IA locale)'}
                </button>
              )}

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
              <ChampsEvenement form={form} setForm={setForm} categories={categories} />
              <div className="flex items-center gap-2">
                <button type="button" disabled={!form.titre.trim()}
                  onClick={() => { onChange(corpsJalon(form)); setEdition(false) }}
                  className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md disabled:opacity-40">
                  Enregistrer
                </button>
                <button type="button" onClick={() => { setForm(formDepuis(jalon)); setEdition(false) }}
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
  // Mois d'ouverture de la modale d'ajout ; null = fermée. On garde le mois car l'ajout
  // peut partir de l'en-tête d'un mois précis autant que du bouton général.
  const [ajout, setAjout] = useState<number | null>(null)
  // Ajouts/modifications/suppressions non encore exportés vers un agenda extérieur.
  // Relu du stockage local à chaque changement de dossier — le décalage avec l'agenda de
  // l'utilisateur survit à un rechargement de page, il doit donc survivre à l'état React.
  const [changements, setChangements] = useState<Changements>(() => lireChangements(slug))
  useEffect(() => { setChangements(lireChangements(slug)) }, [slug])
  useEffect(() => { ecrireChangements(slug, changements) }, [slug, changements])
  const [installe, setInstalle] = useState(false)      // installation du retroplanning livre en cours
  const [vue, setVue] = useState<'cartes' | 'calendrier'>('cartes')
  const [curseur, setCurseur] = useState(() => new Date())   // mois affiche par le calendrier
  const [charge, setCharge] = useState<Date | null>(null)    // instant du dernier chargement reussi
  const [rafraichit, setRafraichit] = useState(false)
  const [, battement] = useState(0)

  /**
   * Recharge le planning depuis le backend. `silencieux` = on ne démonte pas la vue : la
   * fiche ouverte le reste, le défilement ne saute pas, seul le bouton tourne. C'est ce
   * qui permet d'actualiser sans perdre ce qu'on était en train de lire.
   *
   * Un appel relit TOUT ce dont dépend l'agenda : les jalons et leur suivi, ET la date du
   * terme (que le backend relit en base à chaque requête). Changer le terme dans les
   * Paramètres depuis un autre onglet est donc répercuté par ce bouton.
   */
  const charger = (silencieux = false) => {
    silencieux ? setRafraichit(true) : setLoading(true)
    dossiersApi.planning(slug)
      .then(p => { setPlanning(p); setCharge(new Date()) })
      .catch(() => toast.error('Planning indisponible'))
      .finally(() => { setLoading(false); setRafraichit(false) })
  }
  useEffect(() => { charger() }, [slug])

  // Le libellé de fraîcheur doit VIEILLIR à l'écran. Sans ce battement il resterait figé
  // sur « à l'instant » — précisément le mensonge qu'on cherche à supprimer.
  useEffect(() => {
    const t = setInterval(() => battement(n => n + 1), 30_000)
    return () => clearInterval(t)
  }, [])

  /**
   * Un agenda ouvert depuis ce matin ment. On relit donc en revenant sur l'onglet, si les
   * données ont plus d'une minute — assez pour rattraper une modification faite ailleurs
   * (autre onglet, autre poste), pas assez pour marteler l'API à chaque aller-retour.
   */
  useEffect(() => {
    const auRetour = () => {
      if (document.visibilityState !== 'visible') return
      if (charge && Date.now() - charge.getTime() < 60_000) return
      charger(true)
    }
    document.addEventListener('visibilitychange', auRetour)
    window.addEventListener('focus', auRetour)
    return () => {
      document.removeEventListener('visibilitychange', auRetour)
      window.removeEventListener('focus', auRetour)
    }
  }, [charge, slug])

  // Le calendrier s'ouvre sur aujourd'hui si le planning couvre cette date, sinon sur son
  // premier jalon daté : une grossesse qui commence dans trois mois n'a rien à montrer
  // du mois courant, et tomber sur une grille vide donne l'impression d'un bug.
  useEffect(() => {
    if (!planning) return
    const dates = planning.mois.flatMap(m => m.jalons)
      .map(j => j.date_prevue).filter((d): d is string => Boolean(d))
    if (!dates.length) return
    const debut = dates.reduce((a, b) => (a < b ? a : b))
    const fin = dates.reduce((a, b) => (a > b ? a : b))
    const auj = iso(new Date())
    if (auj < debut || auj > fin) setCurseur(new Date(`${debut}T00:00:00`))
  }, [planning])

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

  // Le calendrier et l'export n'ont plus besoin du terme dès qu'un rendez-vous est daté :
  // un événement saisi au jour près se pose tout seul, sans rien calculer.
  const aDesDates = useMemo(
    () => planning?.mois.some(m => m.jalons.some(j => j.date_prevue)) ?? false, [planning])

  const jalonOuvert = useMemo(() => {
    for (const m of planning?.mois ?? []) {
      const j = m.jalons.find(x => x.id === ouvert)
      if (j) return { jalon: j, mois: m }
    }
    return null
  }, [planning, ouvert])

  // ── Changements non exportés ───────────────────────────────────────────────
  // Ce qui se retrouve dans le fichier .ics — et donc ce qui rend l'agenda extérieur
  // périmé quand ça change. Cocher un jalon ou écrire une note personnelle n'en fait pas
  // partie : ni l'un ni l'autre ne sort à l'export, les signaler serait du bruit.
  const CHAMPS_EXPORTES = ['titre', 'detail', 'categorie', 'echeance', 'url', 'sa',
    'mois', 'date_reelle', 'heure_debut', 'heure_fin']

  const noterChange = (id: string) => setChangements(c =>
    c.ids.includes(id) ? c : { ...c, ids: [...c.ids, id] })
  const noterSuppression = (id: string) => setChangements(c =>
    ({ ids: c.ids.filter(x => x !== id), suppressions: c.suppressions + 1 }))
  // Exporter un événement seul ne solde QUE celui-là : le reste du planning n'a pas bougé
  // dans l'agenda de l'utilisateur pour autant.
  const noterExport = (id?: string) => setChangements(c =>
    id ? { ...c, ids: c.ids.filter(x => x !== id) } : AUCUN_CHANGEMENT)

  // ── Actions ────────────────────────────────────────────────────────────────
  const majJalon = async (id: string, data: Parameters<typeof dossiersApi.updateJalon>[1]) => {
    try {
      const maj = await dossiersApi.updateJalon(id, data)
      if (Object.keys(data).some(k => CHAMPS_EXPORTES.includes(k))) noterChange(id)
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
      noterSuppression(j.id)
      toast.success('Jalon retiré')
      charger(true)
    } catch { toast.error('Suppression échouée') }
  }

  // Rejoue le seed du dossier : idempotent côté backend, il n'ajoute que les jalons absents
  // et ne touche jamais au suivi personnel déjà saisi.
  const installerLivre = async () => {
    setInstalle(true)
    try {
      const r = await dossiersApi.installerSeed(slug)
      toast.success(`${r.jalons_ajoutes} jalon(s) installé(s)`)
      charger(true)
    } catch {
      toast.error("Aucun rétroplanning n'est livré pour ce dossier")
    } finally {
      setInstalle(false)
    }
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
          <Link to="/settings?section=set-dossiers"
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

          {/* L'ajout vit dans l'en-tête, pas dans un mois : on ajoute un événement au
              planning, et c'est sa date qui décide de sa place. Le « + » de chaque mois
              reste pour l'ajout non daté, mais il n'était visible de personne. */}
          <button type="button" onClick={() => setAjout(moisCourant ?? 0)}
            title="Ajouter un événement au planning (rendez-vous daté ou repère de période)"
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors">
            <CalendarPlus size={13} />
            Ajouter un événement
          </button>

          {/* Un agenda est un instantané : il faut pouvoir le redemander, et savoir de quand
              il date. Le libellé est aussi important que le bouton. */}
          <button type="button" onClick={() => charger(true)} disabled={rafraichit}
            title="Relire les jalons, leur suivi et la date du terme depuis le serveur"
            className="flex items-center gap-1.5 px-2 py-1 text-xs text-gray-500 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-50 transition-colors">
            <RefreshCw size={12} className={clsx(rafraichit && 'animate-spin')} />
            <span className="hidden sm:inline">{rafraichit ? 'Actualisation…' : 'Actualiser'}</span>
          </button>
          <span className="text-[11px] text-gray-400" title={charge ? charge.toLocaleString('fr-FR') : undefined}>
            {fraicheur(charge)}
          </span>

          {/* Export iCalendar. Un vrai lien, pas un téléchargement piloté en JS : c'est la
              seule voie fiable quand l'application est servie en HTTP. Affiché seulement si
              une date de terme existe — sans elle, aucun jalon n'a de date à exporter. */}
          {(planning.date_terme || aDesDates) && (
            <a href={dossiersApi.planningIcsUrl(slug)} download onClick={() => noterExport()}
              title="Télécharger le planning au format iCalendar (.ics), à importer dans n'importe quel agenda"
              className="flex items-center gap-1.5 px-2 py-1 text-xs text-gray-500 border border-gray-200 rounded-md hover:bg-gray-50 transition-colors">
              <Download size={12} />
              <span className="hidden sm:inline">Exporter (.ics)</span>
            </a>
          )}
        </div>
        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div className="h-full bg-emerald-400 transition-all" style={{ width: `${pourcent}%` }} />
        </div>

        {/* L'agenda de l'utilisateur est une COPIE : elle ne bouge que s'il réimporte. Sans
            ce rappel, un planning modifié cinq fois se décale en silence de l'agenda qui lui
            sert vraiment — et il n'a aucun moyen de savoir quand refaire l'export. */}
        {(changements.ids.length > 0 || changements.suppressions > 0) && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded-md px-2.5 py-2">
            <CalendarClock size={14} className="shrink-0 text-amber-600" />
            <span className="flex-1 min-w-48">
              {changements.ids.length > 0 && (
                <>
                  <strong>{changements.ids.length}</strong> événement
                  {changements.ids.length > 1 ? 's' : ''} ajouté
                  {changements.ids.length > 1 ? 's' : ''} ou modifié
                  {changements.ids.length > 1 ? 's' : ''} depuis votre dernier export.
                </>
              )}
              {changements.suppressions > 0 && (
                <> {changements.suppressions} retiré{changements.suppressions > 1 ? 's' : ''} du
                  planning — <strong>un réimport ne les enlève pas</strong> de votre agenda,
                  c'est à faire là-bas.</>
              )}
            </span>
            {(planning.date_terme || aDesDates) && (
              <a href={dossiersApi.planningIcsUrl(slug)} download onClick={() => noterExport()}
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-white bg-amber-600 rounded-md hover:bg-amber-700 transition-colors">
                <Download size={12} /> Exporter le planning (.ics)
              </a>
            )}
            <button type="button" onClick={() => noterExport()}
              title="Masquer ce rappel sans exporter"
              className="text-amber-600 hover:text-amber-800" aria-label="Masquer le rappel">
              <X size={13} />
            </button>
          </div>
        )}

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
        {/* Chaque filtre porte la COULEUR de sa catégorie — la même que l'icône de l'événement
            dans le calendrier. Sans ça, le filtre et la grille parlaient deux langues : on
            cochait « Médical » sans savoir quelles pastilles allaient disparaître. */}
        {Object.entries(comptesParCat).sort((a, b) => b[1] - a[1]).map(([c, n]) => {
          const { Icon, fond, texte, puce } = catMeta(c)
          const actif = catFiltre === c
          return (
            <button key={c} type="button" onClick={() => setCatFiltre(x => x === c ? null : c)}
              className={clsx('flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-full border transition-colors',
                actif ? `${fond} ${texte} border-current` : 'border-gray-200 text-gray-500 hover:bg-gray-50')}>
              <Icon size={12} className={actif ? undefined : texte} />
              {planning.categories[c] ?? c}
              <span className={clsx('inline-block w-1.5 h-1.5 rounded-full', puce)} aria-hidden />
              ({n})
            </button>
          )
        })}
        <button type="button" onClick={() => setResteSeul(r => !r)}
          className={clsx('ml-auto flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-full border transition-colors',
            resteSeul ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-gray-200 text-gray-500 hover:bg-gray-50')}>
          <Check size={12} /> Reste à faire
        </button>

        {/* Bascule de vue. Les deux répondent à deux questions : « qu'y a-t-il à faire à
            cette période » (cartes) et « qu'est-ce qui tombe ce mois-ci » (calendrier). */}
        <div className="flex items-center rounded-full border border-gray-200 overflow-hidden">
          {([
            { cle: 'cartes', label: 'Cartes', Icon: LayoutGrid },
            { cle: 'calendrier', label: 'Calendrier', Icon: CalendarDays },
          ] as const).map(({ cle, label, Icon }) => (
            <button key={cle} type="button" onClick={() => setVue(cle)}
              aria-pressed={vue === cle}
              className={clsx('flex items-center gap-1 px-2.5 py-1 text-xs transition-colors',
                vue === cle ? 'bg-blue-50 text-blue-800' : 'text-gray-500 hover:bg-gray-50')}>
              <Icon size={12} /> {label}
            </button>
          ))}
        </div>
      </div>

      {vue === 'calendrier' ? (
        planning.date_terme || aDesDates ? (
          <VueCalendrier planning={planning} jalons={mois.flatMap(m => m.jalons)}
            curseur={curseur} setCurseur={setCurseur} onOuvre={setOuvert} />
        ) : (
          // Sans terme NI rendez-vous daté, aucun jalon n'a de date : un calendrier vide
          // vaudrait moins que rien. Les deux issues sont proposées.
          <div className="text-center py-10 space-y-2">
            <p className="text-sm text-gray-500">
              La vue calendrier a besoin d'une date : celle du terme, ou un événement daté.
            </p>
            <Link to="/settings?section=set-dossiers" className="text-sm text-blue-600 hover:underline">
              Saisir la date du terme
            </Link>
            <p>
              <button type="button" onClick={() => setAjout(0)}
                className="text-sm text-blue-600 hover:underline">
                ou ajouter un événement daté
              </button>
            </p>
          </div>
        )
      ) : (<>

      {/* Mois */}
      {mois.length === 0 && (
        stats.total === 0 ? (
          // Un dossier installé AVANT que le planning n'existe n'a pas ses jalons : le seed
          // est idempotent, mais encore faut-il savoir qu'il faut le rejouer. On le propose ici
          // plutôt que de laisser un onglet vide sans explication.
          <div className="text-center py-10 space-y-3">
            <p className="text-sm text-gray-400">Ce dossier n'a pas encore de rétroplanning.</p>
            <div className="flex flex-wrap items-center justify-center gap-2">
              <button type="button" onClick={installerLivre} disabled={installe}
                className="inline-flex items-center gap-1.5 px-3 py-2 text-sm border border-blue-200 text-blue-600 rounded-lg hover:bg-blue-50 disabled:opacity-40">
                {installe ? <LoadingSpinner size={14} /> : <Plus size={14} />}
                Installer le rétroplanning livré
              </button>
              <button type="button" onClick={() => setAjout(0)}
                className="inline-flex items-center gap-1.5 px-3 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                <CalendarPlus size={14} /> Ajouter un événement
              </button>
            </div>
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
              <button type="button" onClick={() => setAjout(m.index)}
                title="Ajouter un événement à ce mois"
                className="p-0.5 text-gray-300 hover:text-blue-600 transition-colors">
                <Plus size={14} />
              </button>
            </div>

            <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
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
                        {j.date_reelle && (
                          <p className="flex items-center gap-1 text-[11px] mt-1 text-blue-700 font-medium">
                            <Clock size={10} className="shrink-0" />
                            {jolieDate(j.date_reelle)}
                            {j.heure_debut && <> · {joliCreneau(j.heure_debut, j.heure_fin)}</>}
                          </p>
                        )}
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

            </div>
          </section>
        )
      })}

      </>)}

      {jalonOuvert && (
        <FicheJalon
          jalon={jalonOuvert.jalon}
          mois={jalonOuvert.mois}
          slug={slug}
          categories={planning.categories}
          onFerme={() => setOuvert(null)}
          onChange={data => majJalon(jalonOuvert.jalon.id, data)}
          onSupprime={() => supprimer(jalonOuvert.jalon)}
        />
      )}

      {ajout !== null && (
        <ModaleEvenement
          slug={slug}
          moisInitial={ajout}
          categories={planning.categories}
          onFerme={() => setAjout(null)}
          // La modale reste ouverte pour proposer l'export : on recharge derrière elle.
          onAjoute={j => { noterChange(j.id); charger(true) }}
          onExporte={noterExport}
        />
      )}
    </div>
  )
}
