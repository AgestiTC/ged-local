/**
 * Page Dossier thématique — la page dynamique d'un sujet de veille.
 * Ressources groupées dans l'ordre du dossier (le groupe porte une progression, pas
 * un classement), filtrables par type / langue / favoris / recherche plein texte.
 * Le filtrage est CLIENT : un dossier tient dans la centaine d'entrées, inutile de
 * faire un aller-retour réseau par clic. Backend : /api/dossiers/{slug}.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft, BookOpen, Check, ChevronDown, Clapperboard, Copy, ExternalLink, Film, FlaskConical,
  FolderTree, Library, Link as LinkIcon, Newspaper, Pencil, Plus, Podcast, Radio, ScrollText, Search, Sparkles,
  Star, Trash2, Tv, Users, Video, Youtube,
} from 'lucide-react'
import { clsx } from 'clsx'
import { dossiersApi, type DossierDetail, type Ressource, type RessourceInput } from '../api'
import { useToast } from '../components/common/Toast'
import LoadingSpinner from '../components/common/LoadingSpinner'
import { copierTexte } from '../utils/clipboard'

/** Libellé + icône par type. Un type inconnu (ajouté côté backend) retombe sur « lien ». */
const TYPE_META: Record<string, { label: string; Icon: typeof Podcast }> = {
  podcast: { label: 'Podcast', Icon: Podcast },
  chaine: { label: 'Chaîne', Icon: Youtube },
  video: { label: 'Vidéo', Icon: Video },
  documentaire: { label: 'Documentaire', Icon: Clapperboard },
  emission: { label: 'Émission', Icon: Tv },
  film: { label: 'Film', Icon: Film },
  serie: { label: 'Série', Icon: Tv },
  livre: { label: 'Livre', Icon: BookOpen },
  bd: { label: 'BD', Icon: BookOpen },
  article: { label: 'Article', Icon: Newspaper },
  etude: { label: 'Étude', Icon: FlaskConical },
  rapport: { label: 'Rapport', Icon: ScrollText },
  association: { label: 'Association', Icon: Users },
  prompt: { label: 'Prompt IA', Icon: Sparkles },
}
const meta = (type: string) => TYPE_META[type] ?? { label: type, Icon: LinkIcon }

/**
 * Destination cliquable d'une ressource : son URL si elle existe, sinon une recherche CIBLÉE selon
 * le type — Babelio pour un livre (description/résumé), Allociné pour un film (synopsis), YouTube
 * pour une chaîne, Google Scholar pour une étude… AUCUNE URL inventée : c'est une recherche.
 */
function lienSource(r: { url?: string | null; titre: string; auteur?: string | null; type: string }): string {
  if (r.url) return r.url
  const q = encodeURIComponent(`${r.titre} ${r.auteur ?? ''}`.trim())
  switch (r.type) {
    case 'livre': case 'bd': return `https://www.babelio.com/resultats.php?Recherche=${q}`
    case 'film': case 'documentaire': case 'emission': case 'serie': return `https://www.allocine.fr/rechercher/?q=${q}`
    case 'chaine': case 'video': return `https://www.youtube.com/results?search_query=${q}`
    case 'podcast': return `https://www.google.com/search?q=${q}%20podcast`
    case 'etude': case 'rapport': return `https://scholar.google.com/scholar?q=${q}`
    default: return `https://duckduckgo.com/?q=${q}`
  }
}

const RESSOURCE_VIDE: RessourceInput = {
  titre: '', auteur: '', type: 'article', url: '', langue: 'fr', groupe: '', note: '', contenu: '',
}

/**
 * Texte long d'une ressource (prompt à copier, extrait, mode d'emploi).
 * Replié par défaut : sinon un seul prompt de 40 lignes noie la liste. La copie passe
 * par `copierTexte` — `navigator.clipboard` est ABSENT quand l'app est servie en HTTP.
 */
function BlocContenu({ texte }: { texte: string }) {
  const [ouvert, setOuvert] = useState(false)
  const [copie, setCopie] = useState(false)

  const copier = async () => {
    const ok = await copierTexte(texte)
    if (!ok) return
    setCopie(true)
    setTimeout(() => setCopie(false), 1800)
  }

  const lignes = texte.split('\n').length

  return (
    <div className="mt-2 border border-gray-200 rounded-md overflow-hidden">
      <div className="flex items-center gap-2 px-2.5 py-1.5 bg-gray-50">
        <button type="button" onClick={() => setOuvert(o => !o)} aria-expanded={ouvert}
          className="flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-800">
          <ChevronDown size={13} className={clsx('transition-transform', !ouvert && '-rotate-90')} />
          {ouvert ? 'Masquer le texte' : `Voir le texte complet (${lignes} lignes)`}
        </button>
        <button type="button" onClick={copier} title="Copier le texte intégral"
          className="ml-auto flex items-center gap-1 px-2 py-0.5 text-xs text-blue-600 border border-blue-200 rounded hover:bg-blue-50">
          {copie ? <Check size={12} /> : <Copy size={12} />} {copie ? 'Copié' : 'Copier'}
        </button>
      </div>
      {ouvert && (
        <pre className="px-3 py-2.5 text-xs leading-relaxed text-gray-700 whitespace-pre-wrap break-words max-h-96 overflow-y-auto bg-white font-mono">
          {texte}
        </pre>
      )}
    </div>
  )
}

export default function DossierDetailPage() {
  const { slug = '' } = useParams()
  const toast = useToast()
  const [dossier, setDossier] = useState<DossierDetail | null>(null)
  const [loading, setLoading] = useState(true)

  // Filtres (client)
  const [recherche, setRecherche] = useState('')
  const [typeFiltre, setTypeFiltre] = useState<string | null>(null)
  const [langueFiltre, setLangueFiltre] = useState<string | null>(null)
  const [favorisSeuls, setFavorisSeuls] = useState(false)
  const [voirArchivees, setVoirArchivees] = useState(false)

  // Édition
  const [ajout, setAjout] = useState(false)
  const [form, setForm] = useState<RessourceInput>(RESSOURCE_VIDE)
  const [editionId, setEditionId] = useState<string | null>(null)

  // Sous-dossiers (hiérarchie)
  const [ajoutSous, setAjoutSous] = useState(false)
  const [sousTitre, setSousTitre] = useState('')

  const charger = () => {
    setLoading(true)
    dossiersApi.get(slug)
      .then(setDossier)
      .catch(() => toast.error('Dossier introuvable'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { charger() }, [slug])

  const creerSousDossier = async () => {
    const t = sousTitre.trim()
    if (!t || !dossier) return
    try {
      await dossiersApi.create({ titre: t, parent: dossier.slug })
      setSousTitre(''); setAjoutSous(false)
      toast.success('Sous-dossier créé')
      charger()
    } catch { toast.error('Création impossible (un dossier utilise peut-être déjà ce nom).') }
  }

  // Compteurs par type, calculés sur les ressources visibles hors filtre de type :
  // les chiffres des puces restent cohérents avec la recherche en cours.
  const base = useMemo(() => {
    if (!dossier) return []
    const q = recherche.trim().toLowerCase()
    return dossier.ressources.filter(r => {
      if (!voirArchivees && !r.active) return false
      if (favorisSeuls && !r.favori) return false
      if (langueFiltre && r.langue !== langueFiltre) return false
      if (!q) return true
      return [r.titre, r.auteur, r.note, r.contenu, r.groupe, ...(r.tags || [])]
        .filter(Boolean).join(' ').toLowerCase().includes(q)
    })
  }, [dossier, recherche, langueFiltre, favorisSeuls, voirArchivees])

  const comptesParType = useMemo(() => {
    const c: Record<string, number> = {}
    for (const r of base) c[r.type] = (c[r.type] ?? 0) + 1
    return c
  }, [base])

  const visibles = useMemo(
    () => (typeFiltre ? base.filter(r => r.type === typeFiltre) : base),
    [base, typeFiltre],
  )

  // Groupes dans l'ordre du dossier, vides retirés (un filtre ne doit pas laisser de titre orphelin).
  const sections = useMemo(() => {
    if (!dossier) return []
    return dossier.groupes
      .map(g => ({ groupe: g, items: visibles.filter(r => (r.groupe || 'Sans groupe') === g) }))
      .filter(s => s.items.length > 0)
  }, [dossier, visibles])

  const langues = useMemo(
    () => Array.from(new Set((dossier?.ressources ?? []).map(r => r.langue))).sort(),
    [dossier],
  )

  const filtresActifs = Boolean(recherche || typeFiltre || langueFiltre || favorisSeuls)
  const reinitialiser = () => {
    setRecherche(''); setTypeFiltre(null); setLangueFiltre(null); setFavorisSeuls(false)
  }

  // ── Actions ────────────────────────────────────────────────────────────────
  const enregistrer = async () => {
    if (!form.titre?.trim()) return
    const payload: RessourceInput = {
      ...form,
      titre: form.titre.trim(),
      auteur: form.auteur?.trim() || null,
      url: form.url?.trim() || null,
      groupe: form.groupe?.trim() || null,
      note: form.note?.trim() || null,
      contenu: form.contenu?.trim() || null,
    }
    try {
      if (editionId) {
        await dossiersApi.updateRessource(editionId, payload)
        toast.success('Ressource modifiée')
      } else {
        await dossiersApi.addRessource(slug, payload)
        toast.success('Ressource ajoutée')
      }
      setAjout(false); setEditionId(null); setForm(RESSOURCE_VIDE)
      charger()
    } catch { toast.error('Enregistrement impossible') }
  }

  const editer = (r: Ressource) => {
    setEditionId(r.id)
    setForm({
      titre: r.titre, auteur: r.auteur ?? '', type: r.type, url: r.url ?? '',
      langue: r.langue, groupe: r.groupe ?? '', note: r.note ?? '', contenu: r.contenu ?? '',
      tags: r.tags, favori: r.favori, active: r.active,
    })
    setAjout(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const basculerFavori = async (r: Ressource) => {
    try {
      await dossiersApi.updateRessource(r.id, { favori: !r.favori })
      setDossier(d => d && {
        ...d, ressources: d.ressources.map(x => x.id === r.id ? { ...x, favori: !r.favori } : x),
      })
    } catch { toast.error('Modification impossible') }
  }

  const supprimer = async (r: Ressource) => {
    if (!confirm(`Retirer « ${r.titre} » du dossier ?`)) return
    try {
      await dossiersApi.removeRessource(r.id)
      toast.success('Ressource retirée')
      charger()
    } catch { toast.error('Suppression échouée') }
  }

  if (loading) return <LoadingSpinner label="Chargement du dossier…" className="py-16 justify-center" />
  if (!dossier) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-gray-300">
        <Library size={48} strokeWidth={1} />
        <p className="text-sm">Ce dossier n'existe pas.</p>
        <Link to="/dossiers" className="text-sm text-blue-600">Retour aux dossiers</Link>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-50">
      <div className="max-w-4xl mx-auto p-4 md:p-6 space-y-5">

        {/* En-tête + fil d'Ariane (remonte au parent si sous-dossier) */}
        <header className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <Link to="/dossiers" className="inline-flex items-center gap-1.5 hover:text-gray-700">
              <ArrowLeft size={13} /> Dossiers thématiques
            </Link>
            {dossier.parent && (
              <>
                <span className="text-gray-300">/</span>
                <Link to={`/dossiers/${dossier.parent.slug}`} className="hover:text-gray-700">{dossier.parent.titre}</Link>
              </>
            )}
          </div>
          <h1 className="text-xl font-semibold text-gray-900">{dossier.titre}</h1>
          {dossier.description && (
            <p className="text-sm text-gray-500 max-w-3xl leading-relaxed">{dossier.description}</p>
          )}
          <p className="text-xs text-gray-400">
            {dossier.nb_ressources} ressource{dossier.nb_ressources > 1 ? 's' : ''} ·{' '}
            {dossier.groupes.length} section{dossier.groupes.length > 1 ? 's' : ''}
            {dossier.sous_dossiers.length > 0 && <> · {dossier.sous_dossiers.length} sous-dossier{dossier.sous_dossiers.length > 1 ? 's' : ''}</>}
          </p>
        </header>

        {/* Sous-dossiers (hiérarchie) — cartes navigables + création */}
        <section className="bg-white border border-gray-200 rounded-lg p-3 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
              <FolderTree size={13} className="text-blue-500" /> Sous-dossiers
            </h2>
            <button type="button" onClick={() => setAjoutSous(v => !v)}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">
              <Plus size={13} /> Nouveau sous-dossier
            </button>
          </div>
          {ajoutSous && (
            <form onSubmit={e => { e.preventDefault(); creerSousDossier() }} className="flex items-center gap-2">
              <input autoFocus value={sousTitre} onChange={e => setSousTitre(e.target.value)}
                placeholder="Nom du sous-dossier (ex. « 0-1 an »)"
                className="flex-1 text-sm border border-gray-300 rounded-md px-2.5 py-1.5" />
              <button type="submit" className="text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700">Créer</button>
              <button type="button" onClick={() => { setAjoutSous(false); setSousTitre('') }} className="text-sm px-2 py-1.5 text-gray-500 hover:text-gray-700">Annuler</button>
            </form>
          )}
          {dossier.sous_dossiers.length === 0 ? (
            !ajoutSous && <p className="text-xs text-gray-400">Aucun sous-dossier. Utile pour découper par thème ou par tranche d'âge.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {dossier.sous_dossiers.map(s => (
                <Link key={s.id} to={`/dossiers/${s.slug}`}
                  className="border border-gray-200 rounded-md p-2.5 hover:border-blue-300 hover:bg-blue-50/40 transition-colors">
                  <div className="text-sm font-medium text-gray-800 truncate">{s.titre}</div>
                  <div className="text-[11px] text-gray-400">
                    {s.nb_ressources} ressource{s.nb_ressources > 1 ? 's' : ''}
                    {s.nb_sous_dossiers > 0 && <> · {s.nb_sous_dossiers} sous-dossier{s.nb_sous_dossiers > 1 ? 's' : ''}</>}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>

        {/* Filtres */}
        <section className="bg-white border border-gray-200 rounded-lg p-3 space-y-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input value={recherche} onChange={e => setRecherche(e.target.value)}
                placeholder="Rechercher un titre, un auteur, une note, un tag…"
                className="w-full pl-8 pr-3 py-2 text-sm border border-gray-300 rounded-md bg-white" />
            </div>
            <button type="button" onClick={() => setFavorisSeuls(f => !f)}
              title="N'afficher que les incontournables"
              className={clsx('flex items-center gap-1.5 px-2.5 py-2 text-xs rounded-md border transition-colors',
                favorisSeuls ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-gray-200 text-gray-500 hover:bg-gray-50')}>
              <Star size={13} className={favorisSeuls ? 'fill-current' : ''} /> Essentiels
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <button type="button" onClick={() => setTypeFiltre(null)}
              className={clsx('px-2.5 py-1 text-xs rounded-full border transition-colors',
                !typeFiltre ? 'border-blue-200 bg-blue-50 text-blue-800' : 'border-gray-200 text-gray-500 hover:bg-gray-50')}>
              Tout ({base.length})
            </button>
            {Object.entries(comptesParType)
              .sort((a, b) => b[1] - a[1])
              .map(([type, n]) => {
                const { label, Icon } = meta(type)
                return (
                  <button key={type} type="button" onClick={() => setTypeFiltre(t => t === type ? null : type)}
                    className={clsx('flex items-center gap-1 px-2.5 py-1 text-xs rounded-full border transition-colors',
                      typeFiltre === type ? 'border-blue-200 bg-blue-50 text-blue-800' : 'border-gray-200 text-gray-500 hover:bg-gray-50')}>
                    <Icon size={12} /> {label} ({n})
                  </button>
                )
              })}

            {langues.length > 1 && (
              <span className="flex items-center gap-1.5 ml-1 pl-2 border-l border-gray-200">
                {langues.map(l => (
                  <button key={l} type="button" onClick={() => setLangueFiltre(x => x === l ? null : l)}
                    className={clsx('px-2 py-1 text-xs rounded-full border uppercase transition-colors',
                      langueFiltre === l ? 'border-blue-200 bg-blue-50 text-blue-800' : 'border-gray-200 text-gray-500 hover:bg-gray-50')}>
                    {l}
                  </button>
                ))}
              </span>
            )}

            {filtresActifs && (
              <button type="button" onClick={reinitialiser} className="ml-auto text-xs text-gray-400 hover:text-gray-600">
                Réinitialiser
              </button>
            )}
          </div>
        </section>

        {/* Ajout / édition */}
        <section className="bg-white border border-gray-200 rounded-lg">
          {!ajout ? (
            <button type="button" onClick={() => { setForm(RESSOURCE_VIDE); setEditionId(null); setAjout(true) }}
              className="w-full flex items-center gap-2 px-4 py-3 text-sm text-blue-600 hover:bg-gray-50 rounded-lg transition-colors">
              <Plus size={15} /> Ajouter une ressource
            </button>
          ) : (
            <div className="p-4 space-y-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                {editionId ? 'Modifier la ressource' : 'Nouvelle ressource'}
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <input autoFocus value={form.titre} onChange={e => setForm(f => ({ ...f, titre: e.target.value }))}
                  placeholder="Titre *" className="px-3 py-2 text-sm border border-gray-300 rounded-md bg-white sm:col-span-2" />
                <input value={form.auteur ?? ''} onChange={e => setForm(f => ({ ...f, auteur: e.target.value }))}
                  placeholder="Auteur, producteur, éditeur" className="px-3 py-2 text-sm border border-gray-300 rounded-md bg-white" />
                <input value={form.url ?? ''} onChange={e => setForm(f => ({ ...f, url: e.target.value }))}
                  placeholder="https://…" className="px-3 py-2 text-sm border border-gray-300 rounded-md bg-white" />
                <select value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
                  className="px-3 py-2 text-sm border border-gray-300 rounded-md bg-white">
                  {Object.entries(TYPE_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </select>
                <select value={form.langue} onChange={e => setForm(f => ({ ...f, langue: e.target.value }))}
                  className="px-3 py-2 text-sm border border-gray-300 rounded-md bg-white">
                  <option value="fr">Français</option>
                  <option value="en">Anglais</option>
                </select>
                <input value={form.groupe ?? ''} onChange={e => setForm(f => ({ ...f, groupe: e.target.value }))}
                  placeholder="Section (ex. Podcasts — paternité)" list="groupes-existants"
                  className="px-3 py-2 text-sm border border-gray-300 rounded-md bg-white sm:col-span-2" />
                <datalist id="groupes-existants">
                  {dossier.groupes.map(g => <option key={g} value={g} />)}
                </datalist>
                <textarea value={form.note ?? ''} onChange={e => setForm(f => ({ ...f, note: e.target.value }))}
                  placeholder="Ce que cette ressource apporte de spécifique — c'est elle qui fait la valeur du dossier."
                  rows={2} className="px-3 py-2 text-sm border border-gray-300 rounded-md bg-white sm:col-span-2" />
                <textarea value={form.contenu ?? ''} onChange={e => setForm(f => ({ ...f, contenu: e.target.value }))}
                  placeholder="Texte intégral, si la ressource EST le contenu : prompt à copier, extrait, citation, mode d'emploi. Facultatif."
                  rows={4} className="px-3 py-2 text-xs font-mono border border-gray-300 rounded-md bg-white sm:col-span-2" />
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={enregistrer} disabled={!form.titre?.trim()}
                  className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md disabled:opacity-40">
                  {editionId ? 'Enregistrer' : 'Ajouter'}
                </button>
                <button type="button" onClick={() => { setAjout(false); setEditionId(null); setForm(RESSOURCE_VIDE) }}
                  className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700">
                  Annuler
                </button>
                <label className="ml-auto flex items-center gap-1.5 text-xs text-gray-500">
                  <input type="checkbox" checked={form.favori ?? false}
                    onChange={e => setForm(f => ({ ...f, favori: e.target.checked }))} />
                  Essentiel
                </label>
              </div>
            </div>
          )}
        </section>

        {/* Ressources */}
        {sections.length === 0 && (
          <p className="text-sm text-gray-400 text-center py-10">
            {filtresActifs ? 'Aucune ressource ne correspond à ces filtres.' : 'Ce dossier est vide.'}
          </p>
        )}

        {sections.map(({ groupe, items }) => (
          <section key={groupe}>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
              {groupe} <span className="text-gray-300 normal-case">· {items.length}</span>
            </h2>
            <ul className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
              {items.map(r => {
                const { label, Icon } = meta(r.type)
                return (
                  <li key={r.id} className={clsx('px-4 py-3 group', !r.active && 'opacity-50')}>
                    <div className="flex items-start gap-3">
                      <Icon size={15} className="text-gray-400 mt-0.5 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2 flex-wrap">
                          <a href={lienSource(r)} target="_blank" rel="noopener noreferrer"
                            title={r.url ? 'Ouvrir la source' : 'Chercher la source (aucun lien direct enregistré)'}
                            className="text-sm font-medium text-gray-800 hover:text-blue-600 inline-flex items-center gap-1">
                            {r.titre}
                            {r.url
                              ? <ExternalLink size={11} className="text-gray-400 shrink-0" />
                              : <Search size={11} className="text-gray-300 shrink-0" />}
                          </a>
                          {r.auteur && <span className="text-xs text-gray-400">— {r.auteur}</span>}
                          {r.favori && <Star size={11} className="text-amber-500 fill-current shrink-0" />}
                          {!r.active && <span className="text-[10px] uppercase text-gray-400">archivée</span>}
                        </div>
                        {r.note && <p className="text-xs text-gray-500 mt-1 leading-relaxed">{r.note}</p>}
                        {r.contenu && <BlocContenu texte={r.contenu} />}
                        <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                          <span className="text-[10px] uppercase tracking-wide text-gray-400 border border-gray-200 rounded px-1.5 py-0.5">
                            {label}
                          </span>
                          {r.langue !== 'fr' && (
                            <span className="text-[10px] uppercase tracking-wide text-gray-400 border border-gray-200 rounded px-1.5 py-0.5">
                              {r.langue}
                            </span>
                          )}
                          {(r.tags || []).map(t => (
                            <span key={t} className="text-[10px] text-gray-400">#{t}</span>
                          ))}
                        </div>
                      </div>
                      {/* Actions — visibles au survol sur pointeur fin, toujours au tactile. */}
                      <div className="flex items-center gap-0.5 shrink-0 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
                        <button type="button" onClick={() => basculerFavori(r)} title="Marquer comme essentiel"
                          className="p-1.5 text-gray-300 hover:text-amber-500"><Star size={13} /></button>
                        <button type="button" onClick={() => editer(r)} title="Modifier"
                          className="p-1.5 text-gray-300 hover:text-blue-600"><Pencil size={13} /></button>
                        <button type="button" onClick={() => supprimer(r)} title="Retirer du dossier"
                          className="p-1.5 text-gray-300 hover:text-red-500"><Trash2 size={13} /></button>
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          </section>
        ))}

        <div className="flex items-center justify-between pt-2 pb-6 text-xs text-gray-400">
          <span>
            <Radio size={11} className="inline mr-1" />
            Les disponibilités (replay, éditions) évoluent — vérifie avant usage.
          </span>
          <button type="button" onClick={() => setVoirArchivees(v => !v)} className="hover:text-gray-600">
            {voirArchivees ? 'Masquer les archivées' : 'Afficher les archivées'}
          </button>
        </div>
      </div>
    </div>
  )
}
