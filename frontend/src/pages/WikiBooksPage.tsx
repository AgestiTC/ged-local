/**
 * WikiBooksPage — « Wiki › Liste des livres ».
 * Grille des livres BookStack groupés par étagère.
 *   • Mode LECTURE (cadenas fermé, défaut) : on parcourt/ouvre les livres. Aucune manip possible.
 *   • Mode ÉDITION (cadenas ouvert) : glisser-déposer un livre entre étagères + renommer un livre
 *     ou une étagère EN LIGNE (pas de popup). Tout est répercuté DIRECTEMENT dans BookStack.
 * Auto-refresh régulier (en lecture) pour refléter les changements faits ailleurs.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, Check, ChevronDown, ChevronRight, Library, Loader2, Lock, Pencil, RefreshCw, Search, Unlock, X } from 'lucide-react'
import { wikiApi, type WikiBook, type WikiShelf } from '../api'
import { useWikiPrefsStore } from '../stores/wikiPrefsStore'
import { useToast } from '../components/common/Toast'

const SANS_ETAGERE = '__sans_etagere__'
const REFRESH_MS = 45000
type Groupe = { nom: string; shelfId: number | null; livres: WikiBook[] }
type Drag = { bookId: number; fromShelfId: number | null }

export default function WikiBooksPage() {
  const toast = useToast()
  const [books, setBooks] = useState<WikiBook[]>([])
  const [shelves, setShelves] = useState<WikiShelf[]>([])
  const [configured, setConfigured] = useState(true)
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [indexing, setIndexing] = useState(false)
  const [indexMsg, setIndexMsg] = useState<string | null>(null)
  const [replies, setReplies] = useState<Set<string>>(new Set())
  const shelvesCollapsedDefault = useWikiPrefsStore(s => s.shelvesCollapsedDefault)
  const initReplis = useRef(false)
  const [busy, setBusy] = useState(false)

  // Édition
  const [editMode, setEditMode] = useState(false)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [survol, setSurvol] = useState<string | null>(null)
  const [editLivre, setEditLivre] = useState<{ id: number; val: string } | null>(null)
  const [editShelf, setEditShelf] = useState<{ id: number; val: string } | null>(null)

  const basculerRepli = (nom: string) => setReplies(prev => {
    const s = new Set(prev)
    if (s.has(nom)) s.delete(nom); else s.add(nom)
    return s
  })

  const recharger = useCallback(() => {
    return wikiApi.books()
      .then(r => { setConfigured(r.configured); setBooks(r.books); setShelves(r.shelves ?? []) })
      .catch(() => setConfigured(false))
  }, [])

  const lancerIndexation = () => {
    setIndexing(true); setIndexMsg(null)
    wikiApi.index()
      .then(() => setIndexMsg('Indexation lancée — les pages apparaîtront dans la GED sous la catégorie « livre » (tâche en arrière-plan).'))
      .catch(() => setIndexMsg("Échec du lancement de l'indexation."))
      .finally(() => setIndexing(false))
  }

  useEffect(() => { recharger().finally(() => setLoading(false)) }, [recharger])

  // Auto-refresh : en LECTURE seulement (jamais pendant une édition/manip → pas d'écrasement de saisie),
  // + à chaque retour de focus sur l'onglet.
  const enEdition = editMode || busy || !!editLivre || !!editShelf || !!drag
  const enEditionRef = useRef(enEdition)
  enEditionRef.current = enEdition
  useEffect(() => {
    const tick = () => { if (!enEditionRef.current && document.visibilityState === 'visible') recharger() }
    const id = setInterval(tick, REFRESH_MS)
    window.addEventListener('focus', tick)
    return () => { clearInterval(id); window.removeEventListener('focus', tick) }
  }, [recharger])

  const filtres = books.filter(b =>
    b.name.toLowerCase().includes(q.toLowerCase()) ||
    b.description.toLowerCase().includes(q.toLowerCase()),
  )

  const groupes = useMemo<Groupe[]>(() => {
    const shelfDe = new Map<number, WikiShelf>()
    for (const s of shelves) for (const id of s.book_ids) if (!shelfDe.has(id)) shelfDe.set(id, s)
    const buckets = new Map<string, WikiBook[]>()
    for (const b of filtres) {
      const cle = shelfDe.get(b.id)?.name ?? SANS_ETAGERE
      const arr = buckets.get(cle); if (arr) arr.push(b); else buckets.set(cle, [b])
    }
    const ordonnees: Groupe[] = []
    for (const s of shelves) if (buckets.has(s.name)) ordonnees.push({ nom: s.name, shelfId: s.id, livres: buckets.get(s.name)! })
    if (buckets.has(SANS_ETAGERE)) ordonnees.push({ nom: 'Sans étagère', shelfId: null, livres: buckets.get(SANS_ETAGERE)! })
    return ordonnees
  }, [filtres, shelves])

  useEffect(() => {
    if (initReplis.current || shelves.length === 0) return
    initReplis.current = true
    if (shelvesCollapsedDefault) setReplies(new Set(shelves.map(s => s.name).concat('Sans étagère')))
  }, [shelves, shelvesCollapsedDefault])

  const grouperParEtagere = shelves.length > 0

  // ── Déplacement (drag & drop) ──
  const deposer = async (toShelfId: number | null, toNom: string, e?: DragEvent) => {
    setSurvol(null)
    let d = drag
    if (!d && e) { try { d = JSON.parse(e.dataTransfer.getData('text/plain')) as Drag } catch { /* ignore */ } }
    setDrag(null)
    if (!d || d.fromShelfId === toShelfId) return
    setBusy(true)
    try {
      await wikiApi.deplacerLivre(d.bookId, d.fromShelfId, toShelfId)
      await recharger()
      toast.success(`Livre déplacé vers « ${toNom} »`)
    } catch { toast.error('Déplacement impossible.') } finally { setBusy(false) }
  }

  // ── Renommages inline (répercutés dans BookStack) ──
  // Mise à jour OPTIMISTE de l'état local dès le 200 : le nouveau nom s'affiche
  // instantanément, sans dépendre d'un re-fetch (la liste BookStack peut renvoyer
  // brièvement l'ancien nom juste après le PUT).
  const enregistrerLivre = async () => {
    const e = editLivre; if (!e) return
    const b = books.find(x => x.id === e.id)
    const nom = e.val.trim()
    setEditLivre(null)
    if (!nom || (b && nom === b.name)) return
    setBusy(true)
    try {
      await wikiApi.renommerLivre(e.id, nom)
      setBooks(bs => bs.map(x => (x.id === e.id ? { ...x, name: nom } : x)))
      toast.success('Livre renommé')
    } catch { toast.error('Renommage impossible.') } finally { setBusy(false) }
  }
  const enregistrerShelf = async () => {
    const e = editShelf; if (!e) return
    const g = groupes.find(x => x.shelfId === e.id)
    const ancien = g?.nom
    const nom = e.val.trim()
    setEditShelf(null)
    if (!nom || (g && nom === g.nom)) return
    setBusy(true)
    try {
      await wikiApi.renommerEtagere(e.id, nom)
      setShelves(ss => ss.map(x => (x.id === e.id ? { ...x, name: nom } : x)))
      // Reporter l'état « replié » sur le nouveau nom (la clé de repli = nom d'étagère).
      if (ancien) setReplies(r => { if (!r.has(ancien)) return r; const n = new Set(r); n.delete(ancien); n.add(nom); return n })
      toast.success('Étagère renommée')
    } catch { toast.error('Renommage impossible.') } finally { setBusy(false) }
  }

  const sortirEdition = () => { setEditMode(false); setEditLivre(null); setEditShelf(null); setDrag(null); setSurvol(null) }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b border-gray-200 bg-white flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-base font-bold text-gray-800 flex items-center gap-2">
          <BookOpen size={18} className="text-blue-600" /> Wiki — Liste des livres
          {busy && <Loader2 size={14} className="animate-spin text-gray-400" />}
        </h1>
        <div className="flex items-center gap-2">
          {/* Cadenas : bascule lecture ⇄ édition (évite les manips accidentelles). */}
          <button type="button" onClick={() => (editMode ? sortirEdition() : setEditMode(true))} disabled={!configured}
            title={editMode ? 'Terminer les modifications (verrouiller)' : 'Déverrouiller pour réorganiser / renommer'}
            className={`text-xs flex items-center gap-1.5 px-3 py-1.5 rounded-md border disabled:opacity-50 ${
              editMode ? 'bg-amber-500 text-white border-amber-500 hover:bg-amber-600' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
            {editMode ? <Unlock size={13} /> : <Lock size={13} />} {editMode ? 'Terminer' : 'Modifier'}
          </button>
          <button type="button" onClick={() => recharger()} disabled={!configured} title="Rafraîchir"
            className="text-xs flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw size={13} />
          </button>
          <button type="button" onClick={lancerIndexation} disabled={indexing || !configured}
            title="Lit toutes les pages des livres et les rend cherchables dans la GED (catégorie « livre »)"
            className="text-xs flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
            <RefreshCw size={13} className={indexing ? 'animate-spin' : ''} /> Indexer le wiki
          </button>
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-2.5 text-gray-400" />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Filtrer un livre…"
              className="text-sm border border-gray-200 rounded-md pl-7 pr-2 py-1.5 w-56 focus:outline-none focus:ring-1 focus:ring-blue-400" />
          </div>
        </div>
      </div>
      {indexMsg && <div className="px-4 py-2 text-xs bg-blue-50 text-blue-700 border-b border-blue-100">{indexMsg}</div>}
      {editMode && (
        <div className="px-4 py-1.5 text-[11px] text-amber-700 bg-amber-50 border-b border-amber-100">
          ✏️ Mode édition : glissez un livre d'une étagère à l'autre, cliquez ✏️ pour renommer un livre/une étagère. Tout est appliqué direct dans BookStack. Cliquez « Terminer » pour verrouiller.
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 bg-gray-50">
        {loading ? (
          <div className="flex justify-center py-16"><Loader2 size={22} className="animate-spin text-gray-400" /></div>
        ) : !configured ? (
          <p className="text-sm text-gray-400 text-center py-16">
            BookStack n'est pas configuré — renseigne l'URL et le token dans <strong>Paramètres → BookStack</strong>.
          </p>
        ) : filtres.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-16">Aucun livre.</p>
        ) : grouperParEtagere ? (
          <div className="flex flex-col gap-6">
            {groupes.map(g => {
              const replie = replies.has(g.nom)
              const cible = editMode && survol === g.nom
              const enEditShelf = editShelf?.id === g.shelfId && g.shelfId !== null
              return (
                <section key={g.nom}
                  onDragOver={editMode ? (e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (survol !== g.nom) setSurvol(g.nom) }) : undefined}
                  onDragLeave={editMode ? (e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setSurvol(s => (s === g.nom ? null : s)) }) : undefined}
                  onDrop={editMode ? (e => { e.preventDefault(); deposer(g.shelfId, g.nom, e) }) : undefined}
                  className={cible ? 'rounded-lg ring-2 ring-amber-400 ring-offset-2 min-h-[2rem]' : 'min-h-[2rem]'}>
                  <div className="flex items-center gap-1.5 mb-2.5 group/etagere">
                    <button type="button" onClick={() => basculerRepli(g.nom)} aria-expanded={!replie}
                      className="text-xs font-semibold uppercase tracking-wide text-gray-500 hover:text-gray-700 flex items-center gap-1.5">
                      {replie ? <ChevronRight size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
                      <Library size={14} className="text-blue-500" />
                    </button>
                    {enEditShelf ? (
                      <form onSubmit={ev => { ev.preventDefault(); enregistrerShelf() }} className="flex items-center gap-1">
                        <input autoFocus value={editShelf!.val}
                          onChange={ev => setEditShelf({ id: editShelf!.id, val: ev.target.value })}
                          onKeyDown={ev => { if (ev.key === 'Escape') setEditShelf(null) }}
                          className="text-xs border border-amber-300 rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-amber-400" />
                        <button type="submit" className="p-0.5 text-green-600 hover:text-green-700"><Check size={13} /></button>
                        <button type="button" onClick={() => setEditShelf(null)} className="p-0.5 text-gray-400 hover:text-gray-600"><X size={13} /></button>
                      </form>
                    ) : (
                      <>
                        <button type="button" onClick={() => basculerRepli(g.nom)}
                          className="text-xs font-semibold uppercase tracking-wide text-gray-500 hover:text-gray-700">
                          {g.nom} <span className="text-gray-300 font-normal normal-case">· {g.livres.length}</span>
                        </button>
                        {editMode && g.shelfId !== null && (
                          <button type="button" onClick={() => setEditShelf({ id: g.shelfId!, val: g.nom })} title="Renommer l'étagère"
                            className="p-0.5 text-gray-400 hover:text-amber-600"><Pencil size={12} /></button>
                        )}
                      </>
                    )}
                  </div>
                  {!replie && (
                    <GrilleLivres livres={g.livres} fromShelfId={g.shelfId} editMode={editMode}
                      editLivre={editLivre} setEditLivre={setEditLivre}
                      onDragStart={(bookId) => setDrag({ bookId, fromShelfId: g.shelfId })}
                      onDragEnd={() => { setDrag(null); setSurvol(null) }}
                      onSaveLivre={enregistrerLivre} />
                  )}
                </section>
              )
            })}
          </div>
        ) : (
          <GrilleLivres livres={filtres} fromShelfId={null} editMode={editMode}
            editLivre={editLivre} setEditLivre={setEditLivre}
            onDragStart={() => {}} onDragEnd={() => {}} onSaveLivre={enregistrerLivre} />
        )}
      </div>
    </div>
  )
}

interface GrilleProps {
  livres: WikiBook[]
  fromShelfId: number | null
  editMode: boolean
  editLivre: { id: number; val: string } | null
  setEditLivre: (v: { id: number; val: string } | null) => void
  onDragStart: (bookId: number) => void
  onDragEnd: () => void
  onSaveLivre: () => void
}

/** Grille de cartes. En LECTURE = liens cliquables ; en ÉDITION = cartes draggables + renommage inline. */
function GrilleLivres({ livres, fromShelfId, editMode, editLivre, setEditLivre, onDragStart, onDragEnd, onSaveLivre }: GrilleProps) {
  const carteCls = 'bg-white border border-gray-200 rounded-lg overflow-hidden flex flex-col'
  const couverture = (b: WikiBook) => (
    <div className="aspect-[3/4] bg-gray-100 flex items-center justify-center overflow-hidden">
      {b.cover_url
        ? <img src={b.cover_url} alt="" loading="lazy" className="w-full h-full object-cover" draggable={false} />
        : <BookOpen size={40} className="text-gray-300" />}
    </div>
  )
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
      {livres.map(b => {
        const enEdit = editLivre?.id === b.id
        // ── ÉDITION : carte draggable (pas de navigation), titre renommable en ligne ──
        if (editMode) {
          return (
            <div key={b.id}
              draggable={!enEdit}
              onDragStart={ev => {
                ev.dataTransfer.effectAllowed = 'move'
                ev.dataTransfer.setData('text/plain', JSON.stringify({ bookId: b.id, fromShelfId }))
                onDragStart(b.id)
              }}
              onDragEnd={onDragEnd}
              className={`${carteCls} border-amber-200 ${enEdit ? '' : 'cursor-grab active:cursor-grabbing hover:border-amber-300 hover:shadow-sm'} transition-all`}>
              {couverture(b)}
              <div className="p-2.5 flex-1 flex flex-col gap-1">
                {enEdit ? (
                  <form onSubmit={ev => { ev.preventDefault(); onSaveLivre() }} className="flex items-center gap-1">
                    <input autoFocus value={editLivre!.val}
                      onChange={ev => setEditLivre({ id: b.id, val: ev.target.value })}
                      onKeyDown={ev => { if (ev.key === 'Escape') setEditLivre(null) }}
                      className="flex-1 min-w-0 text-sm border border-amber-300 rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-amber-400" />
                    <button type="submit" className="p-0.5 text-green-600 hover:text-green-700 shrink-0"><Check size={14} /></button>
                    <button type="button" onClick={() => setEditLivre(null)} className="p-0.5 text-gray-400 hover:text-gray-600 shrink-0"><X size={14} /></button>
                  </form>
                ) : (
                  <span className="flex items-start gap-1">
                    <span className="flex-1 text-sm font-medium text-gray-800 leading-tight line-clamp-2">{b.name}</span>
                    <button type="button" onClick={() => setEditLivre({ id: b.id, val: b.name })} title="Renommer le livre"
                      className="shrink-0 p-0.5 text-gray-400 hover:text-amber-600"><Pencil size={12} /></button>
                  </span>
                )}
              </div>
            </div>
          )
        }
        // ── LECTURE : carte-lien cliquable ──
        return (
          <Link key={b.id} to={`/wiki/livres/${b.id}`}
            className={`${carteCls} hover:border-blue-300 hover:shadow-sm transition-all`}>
            {couverture(b)}
            <div className="p-2.5 flex-1 flex flex-col gap-1">
              <span className="text-sm font-medium text-gray-800 leading-tight line-clamp-2">{b.name}</span>
              {b.description && <span className="text-[11px] text-gray-400 line-clamp-2">{b.description}</span>}
            </div>
          </Link>
        )
      })}
    </div>
  )
}
