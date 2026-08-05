/**
 * Page GED — Recherche hybride + panneau latéral fiche document
 * Barre de recherche + filtres + grille de résultats + panneau détail
 */
import { useEffect, useRef, useState } from 'react'
import { Search, X, Tag, FolderOpen, FileText, List, Eye, Download, Copy, Trash2, FolderMinus, Loader2, MonitorPlay, ChevronDown, BookOpen, ExternalLink, Sparkles, Layers, SlidersHorizontal } from 'lucide-react'
import { clsx } from 'clsx'
import { useNavigate } from 'react-router-dom'
import { useGEDStore } from '../stores/gedStore'
import { useDocumentStore } from '../stores/documentStore'
import { useGedSelection } from '../stores/gedSelectionStore'
import DocumentCard from '../components/ged/DocumentCard'
import DocumentPreview from '../components/ged/DocumentPreview'
import AllDocumentsView, { type QuickFilter, type Mode } from '../components/ged/AllDocumentsView'
import LoadingSpinner from '../components/common/LoadingSpinner'
import { documentsApi, corbeilleApi, presentationsApi, suivreJob, assistantApi, regroupementsApi, type PieceProposee, type Etiquette, type QAReponse } from '../api'
import AnswerCard from '../components/ged/AnswerCard'
import { useToast } from '../components/common/Toast'
import type { SearchType, Document } from '../types'

function formatBytes(n?: number) {
  if (!n) return ''
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} Ko`
  return `${(n / 1024 / 1024).toFixed(1)} Mo`
}

const SEARCH_TYPES: { value: SearchType; label: string }[] = [
  { value: 'hybrid', label: 'Hybride' },
  { value: 'text', label: 'Texte' },
  { value: 'semantic', label: 'Sémantique' },
]

const ETIQUETTES: Record<Etiquette, { label: string; classe: string }> = {
  elevee: { label: 'Élevée', classe: 'bg-green-50 text-green-700' },
  moyenne: { label: 'Moyenne', classe: 'bg-amber-50 text-amber-700' },
  faible: { label: 'Faible', classe: 'bg-gray-100 text-gray-500' },
}

/**
 * Pertinence d'un résultat, en clair. On affiche une ÉTIQUETTE plutôt que le % : ce dernier
 * est normalisé par le meilleur du lot, donc le premier résultat vaut toujours ~100 % même
 * quand il est hors-sujet — un chiffre plus trompeur qu'informatif. Le % reste en info-bulle.
 */
function BadgePertinence({ etiquette, pct }: { etiquette?: Etiquette; pct: number }) {
  if (!etiquette) return <span className="text-xs text-blue-600 font-semibold shrink-0">{pct}%</span>
  const { label, classe } = ETIQUETTES[etiquette]
  return (
    <span className={clsx('text-xs font-medium px-1.5 py-0.5 rounded-full shrink-0', classe)}
      title={`Pertinence ${label.toLowerCase()} — score relatif au lot : ${pct} %`}>
      {label}
    </span>
  )
}

export default function GEDPage() {
  const {
    query, searchType,
    results, total, nbPertinents, nbMasques, hasMore, loadingMore, loading, error,
    categories, tags,
    setQuery, setSearchType,
    search, loadMore, clearResults,
    loadTags, loadCategories,
  } = useGEDStore()

  const { selectDocument } = useDocumentStore()
  const navigate = useNavigate()
  const toast = useToast()
  const inputRef = useRef<HTMLInputElement>(null)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [preview, setPreview] = useState<Document | null>(null)  // aperçu fichier (résultats de recherche)

  const telecharger = (id: string, nom: string) => {
    const a = document.createElement('a'); a.href = documentsApi.fileUrl(id, true); a.download = nom; a.click()
  }
  const copierChemin = async (chemin?: string) => {
    if (!chemin) { toast.error('Chemin indisponible'); return }
    try { await navigator.clipboard.writeText(chemin); toast.success('Chemin copié') } catch { toast.error('Copie impossible') }
  }

  // ── Sélection multiple + actions de masse ──
  const selection = useGedSelection()
  const [bulkAction, setBulkAction] = useState<'corbeille' | 'desindexer' | null>(null)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)  // remonte AllDocumentsView après une action de masse
  const [creatingPres, setCreatingPres] = useState(false)
  const [regroupNom, setRegroupNom] = useState<string | null>(null)  // null = modale fermée
  const [creatingRegroup, setCreatingRegroup] = useState(false)

  const creerRegroupement = async () => {
    const nom = (regroupNom ?? '').trim()
    const ids = [...selection.ids]
    if (!nom || ids.length === 0) return
    setCreatingRegroup(true)
    try {
      await regroupementsApi.create({ nom, document_ids: ids })
      toast.success(`Regroupement « ${nom} » créé (${ids.length} doc${ids.length > 1 ? 's' : ''})`)
      setRegroupNom(null)
      selection.clear()
      navigate('/regroupements')
    } catch {
      toast.error('Création du regroupement impossible')
    } finally { setCreatingRegroup(false) }
  }

  const creerPresentation = async () => {
    const ids = [...selection.ids]
    if (ids.length < 2) return
    setCreatingPres(true)
    try {
      // Tâche durable : on met en file puis on suit le job (survit au changement de page).
      const { job_id } = await presentationsApi.creer(ids)
      const job = await suivreJob(job_id)
      if (job.statut === 'completed') {
        const r = job.resultat as { presentation_id?: string; titre?: string; nb_slides?: number } | null
        if (r?.presentation_id) {
          window.open(`/presentation/${r.presentation_id}`, '_blank', 'noopener')
          toast.success(`Présentation « ${r.titre ?? ''} » créée (${r.nb_slides ?? 0} diapos)`)
          selection.clear()
        }
      } else if (job.statut === 'failed') {
        toast.error(`Génération impossible : ${job.erreur ?? 'Ollama ?'}`)
      }
    } catch {
      toast.error('Génération de la présentation impossible (Ollama ?)')
    } finally { setCreatingPres(false) }
  }

  const confirmerBulk = async () => {
    const ids = [...selection.ids]
    if (ids.length === 0) { setBulkAction(null); return }
    setBulkBusy(true)
    let ok = 0, ko = 0
    for (const id of ids) {
      try {
        if (bulkAction === 'corbeille') await corbeilleApi.envoyer(id)
        else await documentsApi.delete(id)
        ok++
      } catch { ko++ }
    }
    setBulkBusy(false)
    setBulkAction(null)
    selection.clear()
    setRefreshKey(k => k + 1)        // rafraîchit la liste « Tout afficher »
    if (!showAll && query) search()  // rafraîchit les résultats de recherche
    const verbe = bulkAction === 'corbeille' ? 'déplacé(s) vers la corbeille' : 'retiré(s) de l\'index'
    ok && toast.success(`${ok} fichier(s) ${verbe}`)
    ko && toast.error(`${ko} échec(s)`)
  }

  // GED « parcourable par défaut » : on ouvre sur la liste (Tout afficher), pas sur une recherche vide.
  const [showAll, setShowAll] = useState(true)
  // Filtre rapide piloté par le rail (catégorie/tag), appliqué à la liste sans requête.
  const [quickFilter, setQuickFilter] = useState<QuickFilter | null>(null)
  // Mode de regroupement (remonté d'AllDocumentsView) — sert à masquer le rail Catégories/Tags
  // quand on regroupe déjà (évite le doublon).
  const [groupBy, setGroupBy] = useState<Mode>('none')
  const [tagSearch, setTagSearch] = useState('')   // filtre de la liste de tags (sidebar)
  const [filtresOpen, setFiltresOpen] = useState(false)  // tiroir de filtres sur mobile (< md)
  const toutAfficher = () => { setShowAll(true); setQuickFilter(null); setSelectedDocId(null); clearResults(); setAssistantPieces(null); setAfficherProposes(false) }

  useEffect(() => {
    loadTags()
    loadCategories()
  }, [])

  // Lancer une recherche → bascule en mode résultats (quitte le mode parcourir)
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (assistantMode) { assistantSub === 'question' ? lancerQuestion() : lancerAssistant(); return }
    setShowAll(false); setQuickFilter(null); setAfficherProposes(false)
    search()
  }

  // Rail : filtrer la liste par catégorie/tag (mode parcourir), sans recherche
  const filtrerCategorie = (categorie: string) => {
    setQuery(''); clearResults(); setSelectedDocId(null)
    setShowAll(true); setQuickFilter({ categorie })
  }
  // Sélection MULTIPLE de tags : chaque clic ajoute/retire le tag (filtre ET). Vide → plus de filtre.
  const filtrerTag = (tag: string) => {
    setQuery(''); clearResults(); setSelectedDocId(null); setShowAll(true)
    setQuickFilter(prev => {
      const cur = prev?.tags ?? []
      const next = cur.includes(tag) ? cur.filter(t => t !== tag) : [...cur, tag]
      return next.length ? { tags: next } : null
    })
  }

  const handleUseInReport = (id: string) => {
    selectDocument(id)
    navigate('/')
  }

  // Liste de tags filtrée par la zone de recherche puis triée A→Z (ordre FR, accents gérés).
  const tagsFiltres = tags
    .filter(t => t.tag.toLowerCase().includes(tagSearch.trim().toLowerCase()))
    .sort((a, b) => a.tag.localeCompare(b.tag, 'fr', { sensitivity: 'base' }))
  const TAGS_MAX = 60   // plafond d'affichage pour éviter une liste gigantesque

  // ── Recherche « Assistant IA » (même moteur que « Créer ») ──────────────────
  // Au lieu d'une liste plate, l'IA déduit les PIÈCES attendues et regroupe les
  // fichiers connus par pièce. Réutilise assistantApi.pieces (page Créer).
  const [assistantMode, setAssistantMode] = useState(false)
  // Sous-mode d'Assistant IA : 📁 constituer un dossier (pièces) | ❓ poser une question (réponse ancrée, E8)
  const [assistantSub, setAssistantSub] = useState<'dossier' | 'question'>('dossier')
  const [assistantPieces, setAssistantPieces] = useState<PieceProposee[] | null>(null)
  const [assistantLoading, setAssistantLoading] = useState(false)
  const lancerAssistant = async () => {
    const besoin = query.trim()
    if (besoin.length < 3) { toast.error('Décris ton besoin (au moins 3 caractères)'); return }
    setShowAll(false); setQuickFilter(null); setSelectedDocId(null)
    setAssistantLoading(true); setAssistantPieces(null)
    try {
      const r = await assistantApi.pieces(besoin)
      setAssistantPieces(r.pieces)
    } catch {
      toast.error('Assistant indisponible (Ollama ?)')
      setAssistantPieces([])
    } finally { setAssistantLoading(false) }
  }

  // ── Sous-mode « Poser une question » (E8) : réponse textuelle ancrée + documents ──
  const [answer, setAnswer] = useState<QAReponse | null>(null)
  const [answerLoading, setAnswerLoading] = useState(false)
  const lancerQuestion = async () => {
    const q = query.trim()
    if (q.length < 3) { toast.error('Pose une question (au moins 3 caractères)'); return }
    setShowAll(false); setQuickFilter(null); setSelectedDocId(null)
    setAnswerLoading(true); setAnswer(null)
    try {
      setAnswer(await assistantApi.question(q))
    } catch {
      toast.error('Assistant indisponible (Ollama ?)')
    } finally { setAnswerLoading(false) }
  }
  // Carte allégée pour une pièce proposée (le shape assistant n'a pas résumé/tags/chemin).
  const carteProposition = (d: PieceProposee['documents'][number]) => (
    <div key={d.id}
      onClick={() => setSelectedDocId(d.id === selectedDocId ? null : d.id)}
      className={clsx('bg-white border rounded-lg p-3 cursor-pointer transition-all hover:shadow-sm',
        d.id === selectedDocId ? 'border-blue-400 shadow-sm' : 'border-gray-200 hover:border-blue-300')}>
      <div className="flex items-start gap-2 mb-2">
        <input type="checkbox" checked={selection.has(d.id)} onClick={e => e.stopPropagation()}
          onChange={() => selection.toggle(d.id)} className="w-4 h-4 accent-amber-600 mt-0.5 shrink-0"
          aria-label={`Sélectionner ${d.nom}`} />
        <FileText size={15} className="text-gray-400 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-800 truncate" title={d.nom}>{d.nom}</p>
          <p className="text-xs text-gray-400">{(d.extension || '').toUpperCase()}{d.categorie ? ` · ${d.categorie}` : ''}</p>
        </div>
        <BadgePertinence etiquette={d.etiquette} pct={Math.round(d.score * 100)} />
      </div>
      <div className="flex items-center gap-1 pt-2 border-t border-gray-100" onClick={e => e.stopPropagation()}>
        <button type="button" title="Aperçu du fichier"
          onClick={() => setPreview({ id: d.id, nom: d.nom, extension: d.extension, chemin: '', chemin_copie: '' } as Document)}
          className="flex items-center gap-1 text-xs px-2 py-1 text-blue-600 hover:bg-blue-50 rounded">
          <Eye size={13} /> Aperçu
        </button>
        <button type="button" title="Fiche IA" onClick={() => setSelectedDocId(d.id)}
          className="flex items-center gap-1 text-xs px-2 py-1 text-violet-600 hover:bg-violet-50 rounded">
          <FileText size={13} /> Fiche
        </button>
        <button type="button" title="Télécharger" onClick={() => telecharger(d.id, d.nom)}
          className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded">
          <Download size={13} />
        </button>
      </div>
    </div>
  )

  // ── Gate de pertinence (backend) ────────────────────────────────────────────
  // Par défaut on n'affiche QUE les résultats pertinents : le % de score est relatif au lot
  // (le meilleur vaut toujours ~100 %, même hors-sujet), donc une liste pleine ne veut rien
  // dire. Quand rien n'est pertinent, on le dit — et « Afficher quand même » révèle les
  // proposés déjà en mémoire (aucun second appel réseau).
  const [afficherProposes, setAfficherProposes] = useState(false)
  const pertinents = results.filter(r => r.pertinent !== false)
  const visibles = afficherProposes ? results : pertinents
  // Testé sur ce que l'on a CHARGÉ, pas sur le compteur global : si une page ne contenait que
  // des non-pertinents, se fier à `nbPertinents > 0` afficherait un écran vide.
  const aucunPertinent = results.length > 0 && pertinents.length === 0

  // ③ Résultats de recherche groupés par PERTINENCE (tranches repliables + Livres épinglés).
  const [groupMode, setGroupMode] = useState<'none' | 'pertinence' | 'type'>('none')
  const [pliees, setPliees] = useState<Set<string>>(new Set())
  const basculerGroupe = (k: string) =>
    setPliees(s => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const estLivre = (r: (typeof results)[number]) => (r.metadonnees_ia?.categorie || '').toLowerCase() === 'livre'
  const pct = (r: (typeof results)[number]) => r.pertinence ?? Math.round((r.score ?? 0) * 100)
  const groupesPertinence = (rs: typeof results) => [
    { key: 'livres', label: '📚 Livres (wiki)', items: rs.filter(estLivre) },
    { key: 'b80', label: '🟢 Très pertinent · 100–80 %', items: rs.filter(r => !estLivre(r) && pct(r) >= 80) },
    { key: 'b50', label: '🟡 Pertinent · 80–50 %', items: rs.filter(r => !estLivre(r) && pct(r) >= 50 && pct(r) < 80) },
    { key: 'b30', label: '🟠 Moyen · 50–30 %', items: rs.filter(r => !estLivre(r) && pct(r) >= 30 && pct(r) < 50) },
    { key: 'b0', label: '🔴 Faible · 30–0 %', items: rs.filter(r => !estLivre(r) && pct(r) < 30) },
  ].filter(g => g.items.length > 0)

  // Regroupement par TYPE de fichier (PDF / Document / Image / Audio…), dérivé de type_groupe.
  const groupesType = (rs: typeof results) => {
    const icones: Record<string, string> = {
      PDF: '📕', Document: '📄', Tableur: '📊', 'Présentation': '📑', Image: '🖼️',
      Audio: '🎵', 'Vidéo': '🎬', Archive: '🗜️', Autre: '📎',
    }
    const ordre = ['PDF', 'Document', 'Tableur', 'Présentation', 'Image', 'Audio', 'Vidéo', 'Archive', 'Autre']
    return ordre.map(t => ({
      key: `type-${t}`,
      label: `${icones[t] ?? '📎'} ${t}`,
      items: rs.filter(r => (r.type_groupe ?? 'Autre') === t),
    })).filter(g => g.items.length > 0)
  }

  const carteResultat = (r: (typeof results)[number]) => (
    <div
      key={r.id}
      onClick={() => setSelectedDocId(r.id === selectedDocId ? null : r.id)}
      className={clsx(
        'bg-white border rounded-lg p-3 cursor-pointer transition-all hover:shadow-sm',
        r.id === selectedDocId ? 'border-blue-400 shadow-sm' : 'border-gray-200 hover:border-blue-300',
        // Proposé malgré le gate → atténué, pour qu'il ne se confonde pas avec un vrai résultat.
        r.pertinent === false && 'opacity-60 border-dashed',
      )}
    >
      <div className="flex items-start gap-2 mb-2">
        <input type="checkbox" checked={selection.has(r.id)} onClick={e => e.stopPropagation()}
          onChange={() => selection.toggle(r.id)} className="w-4 h-4 accent-amber-600 mt-0.5 shrink-0"
          aria-label={`Sélectionner ${r.nom}`} />
        <FileText size={15} className="text-gray-400 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-800 truncate" title={r.nom}>{r.nom}</p>
          <p className="text-xs text-gray-400">{r.extension.toUpperCase()} · {formatBytes(r.taille_octets)}</p>
        </div>
        <BadgePertinence etiquette={r.etiquette} pct={pct(r)} />
      </div>

      {r.metadonnees_ia.resume && (
        <p className="text-xs text-gray-600 line-clamp-2 mb-2 leading-relaxed">{r.metadonnees_ia.resume}</p>
      )}

      <div className="flex flex-wrap gap-1">
        {r.metadonnees_ia.categorie && (
          <span className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded-full flex items-center gap-1">
            <FolderOpen size={9} />{r.metadonnees_ia.categorie}
          </span>
        )}
        {r.metadonnees_ia.tags.slice(0, 3).map(tag => (
          <span key={tag} className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded-full flex items-center gap-1">
            <Tag size={9} />{tag}
          </span>
        ))}
      </div>

      <div className="flex items-center gap-1 mt-2 pt-2 border-t border-gray-100" onClick={e => e.stopPropagation()}>
        {r.wiki_url ? (
          // Carte « livre » (wiki) : on ouvre la page dans le wiki, pas de fichier à télécharger.
          <>
            <a href={r.wiki_url} target="_blank" rel="noopener noreferrer" title="Ouvrir la page dans le wiki"
              className="flex items-center gap-1 text-xs px-2 py-1 text-blue-600 hover:bg-blue-50 rounded">
              <BookOpen size={13} /> Ouvrir dans le wiki <ExternalLink size={11} className="text-blue-400" />
            </a>
            <button type="button" title="Fiche IA" onClick={() => setSelectedDocId(r.id)}
              className="flex items-center gap-1 text-xs px-2 py-1 text-violet-600 hover:bg-violet-50 rounded">
              <FileText size={13} /> Fiche
            </button>
          </>
        ) : (
          <>
            <button type="button" title="Aperçu du fichier"
              onClick={() => setPreview({ id: r.id, nom: r.nom, extension: r.extension, chemin: '', chemin_copie: r.chemin_copie } as Document)}
              className="flex items-center gap-1 text-xs px-2 py-1 text-blue-600 hover:bg-blue-50 rounded">
              <Eye size={13} /> Aperçu
            </button>
            <button type="button" title="Fiche IA" onClick={() => setSelectedDocId(r.id)}
              className="flex items-center gap-1 text-xs px-2 py-1 text-violet-600 hover:bg-violet-50 rounded">
              <FileText size={13} /> Fiche
            </button>
            <button type="button" title="Télécharger" onClick={() => telecharger(r.id, r.nom)}
              className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded">
              <Download size={13} />
            </button>
            <button type="button" title="Copier le chemin (UNC)" onClick={() => copierChemin(r.chemin_copie)}
              className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded">
              <Copy size={13} />
            </button>
          </>
        )}
      </div>
    </div>
  )

  // Contenu des filtres (catégories + tags) — partagé entre l'aside bureau et le tiroir mobile.
  const filtresContenu = (
    <>
      {/* Catégories */}
      {groupBy === 'none' && categories.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Catégories</h3>
          <div className="flex flex-col gap-0.5">
            {quickFilter?.categorie && (
              <button
                onClick={() => setQuickFilter(null)}
                className="text-left text-xs px-2.5 py-1.5 rounded-md text-blue-600 bg-blue-50 flex items-center justify-between"
              >
                <span className="truncate">{quickFilter.categorie}</span>
                <X size={10} />
              </button>
            )}
            {categories.slice(0, 12).filter(c => c.categorie !== quickFilter?.categorie).map(c => (
              <button
                key={c.categorie}
                onClick={() => { filtrerCategorie(c.categorie); setFiltresOpen(false) }}
                className="text-left text-xs px-2.5 py-1.5 rounded-md text-gray-600 hover:bg-gray-50 flex items-center justify-between"
              >
                <span className="truncate">{c.categorie}</span>
                <span className="text-gray-400 shrink-0">{c.nb_documents}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Tags */}
      {groupBy === 'none' && tags.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Tags <span className="text-gray-400 font-normal normal-case">({tags.length})</span>
          </h3>
          <input
            type="search"
            value={tagSearch}
            onChange={e => setTagSearch(e.target.value)}
            placeholder="Rechercher un tag…"
            className="w-full mb-2 px-2 py-1 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
          <div className="flex flex-wrap gap-1">
            {tagsFiltres.slice(0, TAGS_MAX).map(t => (
              <button
                key={t.tag}
                onClick={() => { filtrerTag(t.tag); setFiltresOpen(false) }}
                className={clsx(
                  'text-xs px-2 py-0.5 rounded-full transition-colors',
                  quickFilter?.tags?.includes(t.tag)
                    ? 'bg-blue-100 text-blue-700 font-medium'
                    : 'bg-gray-100 hover:bg-blue-50 hover:text-blue-700 text-gray-600',
                )}
              >
                {t.tag}
              </button>
            ))}
          </div>
          {tagsFiltres.length === 0 && (
            <p className="text-xs text-gray-400 mt-1">Aucun tag ne correspond à « {tagSearch} ».</p>
          )}
          {tagsFiltres.length > TAGS_MAX && (
            <p className="text-xs text-gray-400 mt-1">+{tagsFiltres.length - TAGS_MAX} autres — affine la recherche.</p>
          )}
        </div>
      )}

      {groupBy !== 'none' && (
        <p className="text-xs text-gray-400 leading-relaxed">
          Vue groupée par <strong>{groupBy}</strong> active. Repasse « Grouper par&nbsp;: Aucun »
          pour filtrer par catégorie ou tag ici.
        </p>
      )}
    </>
  )

  // Y a-t-il des filtres à proposer ? (sinon, pas de bouton « Filtres » sur mobile)
  const filtresDisponibles = groupBy === 'none' && (categories.length > 0 || tags.length > 0)

  return (
    <div className="flex h-full overflow-hidden">

      {/* ── Filtres latéraux — fixes sur bureau (≥ md), accessibles via un tiroir sur mobile. ── */}
      <aside className="hidden md:flex w-48 shrink-0 bg-white border-r border-gray-200 p-3 overflow-y-auto flex-col gap-4">
        {filtresContenu}
      </aside>

      {/* Tiroir de filtres sur mobile (< md) : ouvert par le bouton « Filtres » de la barre de recherche. */}
      {filtresOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setFiltresOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <aside className="absolute left-0 top-0 h-full w-64 max-w-[80%] bg-white shadow-xl p-3 overflow-y-auto flex flex-col gap-4"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-gray-700 flex items-center gap-1.5"><SlidersHorizontal size={15} /> Filtres</span>
              <button type="button" onClick={() => setFiltresOpen(false)} className="p-1 text-gray-400 hover:text-gray-700"><X size={16} /></button>
            </div>
            {filtresContenu}
          </aside>
        </div>
      )}

      {/* ── Zone principale ──────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">

        {/* Barre de recherche */}
        <div className="bg-white border-b border-gray-200 p-3">
          <form onSubmit={handleSearch} className="flex gap-2">
            <div className="flex-1 relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                ref={inputRef}
                type="search"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder={assistantMode
                  ? (assistantSub === 'question'
                      ? 'Pose une question — ex. « Où travaillait Thomas en juillet 2018 ? »…'
                      : 'Décris ton besoin — ex. « trouve les factures EDF »…')
                  : 'Rechercher dans vos documents…'}
                className={clsx('w-full pl-9 pr-4 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2',
                  assistantMode ? 'border-violet-300 focus:ring-violet-400' : 'border-gray-200 focus:ring-blue-400')}
                autoFocus
              />
            </div>
            <button
              type="submit"
              disabled={!query.trim() || loading || assistantLoading || answerLoading}
              className={clsx('flex items-center gap-1.5 px-4 py-2 text-white text-sm font-medium rounded-lg disabled:opacity-40 transition-colors',
                assistantMode ? 'bg-violet-600 hover:bg-violet-700' : 'bg-blue-600 hover:bg-blue-700')}
            >
              {assistantMode
                ? (assistantSub === 'question' ? <><Sparkles size={14} /> Répondre</> : <><Sparkles size={14} /> Proposer</>)
                : 'Rechercher'}
            </button>
            <button
              type="button"
              onClick={toutAfficher}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-lg border transition-colors',
                showAll ? 'bg-blue-50 text-blue-700 border-blue-300' : 'text-gray-600 border-gray-200 hover:bg-gray-50',
              )}
              title="Voir tous les documents indexés"
            >
              <List size={14} /> Tout afficher
            </button>
            {(results.length > 0 || query || assistantPieces || answer) && (
              <button
                type="button"
                onClick={() => { setQuery(''); clearResults(); setSelectedDocId(null); setShowAll(true); setAssistantPieces(null); setAnswer(null); setAfficherProposes(false) }}
                className="px-3 py-2 text-gray-400 hover:text-gray-700 border border-gray-200 rounded-lg"
                title="Effacer et revenir à la liste"
              >
                <X size={14} />
              </button>
            )}
          </form>

          {/* Mode de recherche + bascule Assistant IA */}
          <div className="flex items-center gap-1.5 mt-2 text-xs text-gray-500 flex-wrap">
            {/* Filtres (mobile uniquement) — le tiroir latéral remplace l'aside masqué < md */}
            {filtresDisponibles && (
              <button type="button" onClick={() => setFiltresOpen(true)}
                className="md:hidden flex items-center gap-1 px-2 py-0.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">
                <SlidersHorizontal size={12} /> Filtres
              </button>
            )}
            {/* Simple ⇄ Assistant IA */}
            <div className="flex rounded-md border border-gray-200 overflow-hidden">
              <button type="button" onClick={() => setAssistantMode(false)}
                className={clsx('px-2 py-0.5 transition-colors', !assistantMode ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-500 hover:bg-gray-50')}>
                Simple
              </button>
              <button type="button" onClick={() => setAssistantMode(true)}
                title="L'IA déduit les pièces attendues et regroupe les fichiers connus"
                className={clsx('flex items-center gap-1 px-2 py-0.5 transition-colors', assistantMode ? 'bg-violet-50 text-violet-700 font-medium' : 'text-gray-500 hover:bg-gray-50')}>
                <Sparkles size={11} /> Assistant IA
              </button>
            </div>
            {assistantMode ? (
              <>
                {/* Sous-mode : 📁 constituer un dossier | ❓ poser une question (E8) */}
                <div className="flex rounded-md border border-violet-200 overflow-hidden">
                  <button type="button" onClick={() => setAssistantSub('dossier')}
                    title="L'IA déduit les pièces attendues et regroupe les fichiers connus"
                    className={clsx('px-2 py-0.5 transition-colors', assistantSub === 'dossier' ? 'bg-violet-100 text-violet-700 font-medium' : 'text-gray-500 hover:bg-gray-50')}>
                    📁 Constituer un dossier
                  </button>
                  <button type="button" onClick={() => setAssistantSub('question')}
                    title="Pose une question ; l'IA compose une réponse ancrée dans tes documents"
                    className={clsx('px-2 py-0.5 transition-colors', assistantSub === 'question' ? 'bg-violet-100 text-violet-700 font-medium' : 'text-gray-500 hover:bg-gray-50')}>
                    ❓ Poser une question
                  </button>
                </div>
                <span className="text-gray-400">
                  {assistantSub === 'question'
                    ? <>Réponse <strong>ancrée</strong> dans tes documents (n'invente rien).</>
                    : <>L'IA propose les documents pertinents, <strong>groupés par pièce</strong>.</>}
                </span>
              </>
            ) : (
              <>
                <span className="ml-1">Recherche :</span>
                {SEARCH_TYPES.map(t => (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => {
                      if (t.value === searchType) return
                      setSearchType(t.value)
                      // Relance auto si une requête est saisie et qu'on est en mode résultats.
                      if (query.trim() && !showAll) { setShowAll(false); setAfficherProposes(false); search() }
                    }}
                    className={clsx(
                      'px-2 py-0.5 rounded-md transition-colors',
                      searchType === t.value ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-500 hover:bg-gray-50',
                    )}
                  >
                    {t.label}
                  </button>
                ))}
              </>
            )}
          </div>
        </div>

        {/* Résultats */}
        <div className="flex-1 overflow-y-auto p-3">

          {/* Barre d'actions de masse — collée en haut de la liste (reste visible au défilement) */}
          {selection.ids.size > 0 && (
            <div className="sticky top-0 z-30 -mx-3 -mt-3 mb-3 px-4 py-2.5 bg-gray-900/95 backdrop-blur text-white shadow-lg flex items-center gap-3 flex-wrap justify-center">
              <span className="text-sm font-medium">{selection.ids.size} sélectionné{selection.ids.size > 1 ? 's' : ''}</span>
              <button type="button" onClick={() => selection.clear()} className="text-xs text-gray-300 hover:text-white">Tout désélectionner</button>
              <span className="w-px h-5 bg-gray-700" />
              {selection.ids.size >= 2 && (
                <button type="button" onClick={creerPresentation} disabled={creatingPres}
                  className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-700 disabled:opacity-60"
                  title="Générer une présentation (diaporama IA) à partir des fichiers sélectionnés">
                  {creatingPres ? <Loader2 size={15} className="animate-spin" /> : <MonitorPlay size={15} />}
                  {creatingPres ? 'Génération…' : 'Créer une présentation'}
                </button>
              )}
              <button type="button" onClick={() => setRegroupNom('')}
                className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700"
                title="Regrouper ces documents pour une analyse IA réutilisable">
                <Layers size={15} /> Regroupement
              </button>
              <button type="button" onClick={() => setBulkAction('desindexer')}
                className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg hover:bg-gray-800">
                <FolderMinus size={15} /> Désindexer
              </button>
              <button type="button" onClick={() => setBulkAction('corbeille')}
                className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg bg-red-600 hover:bg-red-700">
                <Trash2 size={15} /> Corbeille
              </button>
            </div>
          )}

          {/* ── Mode parcourir (liste + vue groupée + filtre rapide) ── */}
          {showAll && (
            <AllDocumentsView
              key={refreshKey}
              filter={quickFilter}
              onClearFilter={() => setQuickFilter(null)}
              groupBy={groupBy}
              onGroupByChange={setGroupBy}
            />
          )}

          {/* ── Assistant IA · sous-mode « Poser une question » (E8) : réponse ancrée ── */}
          {!showAll && assistantMode && assistantSub === 'question' && (
            <AnswerCard answer={answer} loading={answerLoading} query={query}
              onOpen={id => setSelectedDocId(id)} />
          )}

          {/* ── Résultats « Assistant IA » · sous-mode « Constituer un dossier » (pièces regroupées) ── */}
          {!showAll && assistantMode && assistantSub === 'dossier' && assistantLoading && (
            <div className="flex flex-col items-center justify-center py-16 text-gray-400 gap-2 text-center">
              <Loader2 size={22} className="animate-spin text-violet-500" />
              <p className="text-sm text-gray-600">L'IA déduit les pièces attendues et cherche les fichiers…</p>
            </div>
          )}

          {!showAll && assistantMode && assistantSub === 'dossier' && !assistantLoading && assistantPieces && (() => {
            const totalProp = assistantPieces.reduce((n, p) => n + p.documents.length, 0)
            if (totalProp === 0) return (
              <p className="text-sm text-gray-400 py-12 text-center">Aucun fichier proposé pour « {query} ».</p>
            )
            return (
              <div className="space-y-4">
                <p className="text-xs text-gray-500">
                  Pour « <strong>{query}</strong> » — {totalProp} fichier{totalProp > 1 ? 's' : ''} proposé{totalProp > 1 ? 's' : ''},
                  regroupé{totalProp > 1 ? 's' : ''} par pièce attendue.
                </p>
                {assistantPieces.map((p, i) => (
                  <div key={i}>
                    <div className="flex items-center gap-1.5 mb-2 text-sm font-medium text-gray-700">
                      <FolderOpen size={14} className="text-amber-500" /> {p.libelle}
                      <span className="text-xs text-gray-400 font-normal">· {p.documents.length} proposé{p.documents.length > 1 ? 's' : ''}</span>
                    </div>
                    {p.documents.length === 0 ? (
                      <p className="text-xs text-gray-400 pl-5">Aucun fichier connu pour cette pièce.</p>
                    ) : (
                      <div className={clsx('grid gap-2',
                        selectedDocId ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3')}>
                        {p.documents.map(carteProposition)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )
          })()}

          {!showAll && assistantMode && assistantSub === 'dossier' && !assistantLoading && !assistantPieces && (
            <div className="flex flex-col items-center justify-center py-16 text-gray-300 gap-3">
              <Sparkles size={44} strokeWidth={1} className="text-violet-300" />
              <p className="text-sm">Assistant IA — décris ton besoin en langage naturel</p>
              <p className="text-xs">Ex. « trouve les factures EDF », « contrats signés en 2023 »…</p>
            </div>
          )}

          {!showAll && !assistantMode && loading && (
            <div className="flex justify-center py-12">
              <LoadingSpinner label="Recherche en cours…" />
            </div>
          )}

          {!showAll && !assistantMode && error && <p className="text-sm text-red-500 py-4 text-center">{error}</p>}

          {!showAll && !assistantMode && !loading && results.length === 0 && query && (
            <p className="text-sm text-gray-400 py-12 text-center">Aucun résultat pour « {query} »</p>
          )}

          {/* Des candidats existent, mais aucun ne passe le gate → on le dit, au lieu de faire
              passer des faux positifs pour des résultats. */}
          {!showAll && !assistantMode && !loading && aucunPertinent && !afficherProposes && (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
              <Search size={40} strokeWidth={1} className="text-gray-300" />
              <div>
                <p className="text-sm font-medium text-gray-700">Aucun document pertinent pour « {query} »</p>
                <p className="text-xs text-gray-400 mt-1">
                  La recherche n'a rien trouvé qui corresponde vraiment à votre demande.
                </p>
              </div>
              <button type="button" onClick={() => setAfficherProposes(true)}
                className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors">
                Afficher quand même les {nbMasques} fichier{nbMasques > 1 ? 's' : ''} proposé{nbMasques > 1 ? 's' : ''}
              </button>
            </div>
          )}

          {!showAll && !assistantMode && !loading && results.length === 0 && !query && (
            <div className="flex flex-col items-center justify-center py-16 text-gray-300 gap-3">
              <Search size={44} strokeWidth={1} />
              <p className="text-sm">Recherche hybride full-text + sémantique</p>
              <p className="text-xs">Importez des documents puis lancez une recherche</p>
            </div>
          )}

          {!showAll && !assistantMode && visibles.length > 0 && (
            <>
              {afficherProposes && nbMasques > 0 && (
                <div className="mb-3 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-800 flex items-center gap-2">
                  <span className="shrink-0">⚠️</span>
                  <span className="flex-1">
                    Résultats peu pertinents — affichés à votre demande.
                    {nbPertinents > 0 && <> Les {nbPertinents} premiers restent les plus fiables.</>}
                  </span>
                  <button type="button" onClick={() => setAfficherProposes(false)}
                    className="shrink-0 underline hover:no-underline">Masquer</button>
                </div>
              )}
              <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
                <p className="text-xs text-gray-500">
                  {afficherProposes
                    ? <>{total} fichier{total > 1 ? 's' : ''} proposé{total > 1 ? 's' : ''} — mode {searchType}</>
                    : <>{nbPertinents} résultat{nbPertinents > 1 ? 's' : ''} pertinent{nbPertinents > 1 ? 's' : ''} — mode {searchType}</>}
                  {!afficherProposes && nbMasques > 0 && (
                    <button type="button" onClick={() => setAfficherProposes(true)}
                      className="ml-2 text-gray-400 underline hover:text-gray-600"
                      title="Afficher aussi les fichiers écartés par le filtre de pertinence">
                      +{nbMasques} moins pertinent{nbMasques > 1 ? 's' : ''}
                    </button>
                  )}
                </p>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-gray-400">Grouper :</span>
                  <div className="flex rounded-md border border-gray-200 overflow-hidden text-xs">
                    {([['none', 'Aucun'], ['pertinence', 'Pertinence'], ['type', 'Type']] as const).map(([k, label]) => (
                      <button key={k} type="button" onClick={() => setGroupMode(k)}
                        title={k === 'type' ? 'Regrouper par type de fichier (PDF, Document, Image…)' : k === 'pertinence' ? 'Regrouper par tranches de pertinence' : 'Liste simple'}
                        className={clsx('px-2.5 py-1 transition-colors',
                          groupMode === k ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-50')}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              {groupMode !== 'none' ? (
                (groupMode === 'pertinence' ? groupesPertinence(visibles) : groupesType(visibles)).map(g => {
                  const ouvert = !pliees.has(g.key)
                  return (
                    <div key={g.key} className="mb-3">
                      <button type="button" onClick={() => basculerGroupe(g.key)}
                        className="w-full flex items-center gap-2 px-2 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 rounded">
                        <ChevronDown size={15} className={clsx('text-gray-400 transition-transform shrink-0', !ouvert && '-rotate-90')} />
                        <span className="flex-1 text-left">{g.label}</span>
                        <span className="text-xs text-gray-400">({g.items.length})</span>
                      </button>
                      {ouvert && (
                        <div className={clsx('grid gap-2 mt-1',
                          selectedDocId ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3')}>
                          {g.items.map(carteResultat)}
                        </div>
                      )}
                    </div>
                  )
                })
              ) : (
                <div className={clsx('grid gap-2',
                  selectedDocId ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3')}>
                  {visibles.map(carteResultat)}
                </div>
              )}

              {/* Charger plus */}
              {hasMore && (
                <div className="flex justify-center mt-4">
                  <button
                    onClick={loadMore}
                    disabled={loadingMore}
                    className="flex items-center gap-2 px-5 py-2 text-sm text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 disabled:opacity-40 transition-colors"
                  >
                    {loadingMore ? (
                      <LoadingSpinner size={14} />
                    ) : null}
                    {loadingMore ? 'Chargement…' : 'Charger plus de résultats'}
                  </button>
                </div>
              )}

              {!hasMore && visibles.length > 20 && (
                <p className="text-xs text-gray-400 text-center mt-4">
                  Tous les {visibles.length} résultats sont affichés
                </p>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Panneau latéral fiche document ───────────────── */}
      {selectedDocId && (
        <div className="w-80 shrink-0 overflow-hidden border-l border-gray-200">
          <DocumentCard
            documentId={selectedDocId}
            onClose={() => setSelectedDocId(null)}
            onUseInReport={handleUseInReport}
            onOpenDocument={setSelectedDocId}
          />
        </div>
      )}

      {/* Aperçu fichier (depuis un résultat de recherche) */}
      {preview && <DocumentPreview doc={preview} onClose={() => setPreview(null)} />}

      {/* Création d'un regroupement depuis la sélection */}
      {regroupNom !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => !creatingRegroup && setRegroupNom(null)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2"><Layers size={18} className="text-blue-600" /> Nouveau regroupement</h2>
            <p className="text-sm text-gray-600 mb-3">
              <strong>{selection.ids.size}</strong> document(s) seront regroupés pour une <strong>analyse IA réutilisable</strong>
              (consigne + modèle propres au groupe, rendu exportable).
            </p>
            <input type="text" autoFocus value={regroupNom} onChange={e => setRegroupNom(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') creerRegroupement() }}
              placeholder="Nom du regroupement (ex. Devis chantier 2026)"
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-blue-400" />
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setRegroupNom(null)} disabled={creatingRegroup}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">Annuler</button>
              <button type="button" onClick={creerRegroupement} disabled={creatingRegroup || !regroupNom.trim()}
                className="flex items-center gap-2 px-4 py-2 text-white text-sm rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50">
                {creatingRegroup ? <Loader2 size={16} className="animate-spin" /> : <Layers size={16} />} Créer
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirmation action de masse */}
      {bulkAction && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => !bulkBusy && setBulkAction(null)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2">
              {bulkAction === 'corbeille' ? <Trash2 size={18} className="text-red-600" /> : <FolderMinus size={18} className="text-gray-600" />}
              {bulkAction === 'corbeille' ? 'Déplacer vers la corbeille' : 'Retirer de l\'index'}
            </h2>
            <p className="text-sm text-gray-600 mb-4">
              <strong>{selection.ids.size}</strong> fichier(s) vont être {bulkAction === 'corbeille'
                ? <>déplacés vers <strong>A-SUPPRIMER-MATOTEQUE</strong> (les fichiers ne sont <strong>pas supprimés</strong>, restaurables)</>
                : <>retirés de l'index (les <strong>fichiers du NAS ne sont pas touchés</strong>)</>}.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setBulkAction(null)} disabled={bulkBusy}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">Annuler</button>
              <button type="button" onClick={confirmerBulk} disabled={bulkBusy}
                className={clsx('flex items-center gap-2 px-4 py-2 text-white text-sm rounded-lg disabled:opacity-50',
                  bulkAction === 'corbeille' ? 'bg-red-600 hover:bg-red-700' : 'bg-gray-800 hover:bg-gray-900')}>
                {bulkBusy ? <Loader2 size={16} className="animate-spin" /> : null} Confirmer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
