/**
 * WikiBooksPage — « Wiki › Liste des livres ».
 * Grille des livres BookStack groupés par étagère. On peut :
 *   • glisser-déposer un livre d'une étagère à l'autre (ou vers « Sans étagère » = détacher),
 *   • renommer un livre (✏️ sur la carte) ou une étagère (✏️ sur l'en-tête).
 * Tout est répercuté DIRECTEMENT dans BookStack (aucune étape de synchro séparée).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, ChevronDown, ChevronRight, Library, Loader2, Pencil, RefreshCw, Search } from 'lucide-react'
import { wikiApi, type WikiBook, type WikiShelf } from '../api'
import { useWikiPrefsStore } from '../stores/wikiPrefsStore'
import { useToast } from '../components/common/Toast'

const SANS_ETAGERE = '__sans_etagere__'
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
  const [replies, setReplies] = useState<Set<string>>(new Set())   // étagères repliées (par nom)
  const shelvesCollapsedDefault = useWikiPrefsStore(s => s.shelvesCollapsedDefault)
  const initReplis = useRef(false)
  const [drag, setDrag] = useState<Drag | null>(null)              // livre en cours de déplacement
  const [survol, setSurvol] = useState<string | null>(null)        // étagère survolée (feedback dépôt)
  const [busy, setBusy] = useState(false)

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

  const filtres = books.filter(b =>
    b.name.toLowerCase().includes(q.toLowerCase()) ||
    b.description.toLowerCase().includes(q.toLowerCase()),
  )

  // Regroupe les livres filtrés par étagère (avec l'id d'étagère pour les déplacements).
  const groupes = useMemo<Groupe[]>(() => {
    const shelfDe = new Map<number, WikiShelf>()   // book_id → 1re étagère
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
  const deposer = async (toShelfId: number | null, toNom: string) => {
    setSurvol(null)
    const d = drag; setDrag(null)
    if (!d || d.fromShelfId === toShelfId) return
    setBusy(true)
    try {
      await wikiApi.deplacerLivre(d.bookId, d.fromShelfId, toShelfId)
      await recharger()
      toast.success(`Livre déplacé vers « ${toNom} »`)
    } catch { toast.error('Déplacement impossible.') } finally { setBusy(false) }
  }

  // ── Renommages (répercutés dans BookStack) ──
  const renommerLivre = async (b: WikiBook) => {
    const nom = prompt('Nouveau nom du livre :', b.name)
    if (nom === null || !nom.trim() || nom.trim() === b.name) return
    setBusy(true)
    try { await wikiApi.renommerLivre(b.id, nom.trim()); await recharger(); toast.success('Livre renommé') }
    catch { toast.error('Renommage impossible.') } finally { setBusy(false) }
  }
  const renommerEtagere = async (g: Groupe) => {
    if (g.shelfId === null) return
    const nom = prompt("Nouveau nom de l'étagère :", g.nom)
    if (nom === null || !nom.trim() || nom.trim() === g.nom) return
    setBusy(true)
    try { await wikiApi.renommerEtagere(g.shelfId, nom.trim()); await recharger(); toast.success('Étagère renommée') }
    catch { toast.error('Renommage impossible.') } finally { setBusy(false) }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b border-gray-200 bg-white flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-base font-bold text-gray-800 flex items-center gap-2">
          <BookOpen size={18} className="text-blue-600" /> Wiki — Liste des livres
          {busy && <Loader2 size={14} className="animate-spin text-gray-400" />}
        </h1>
        <div className="flex items-center gap-2">
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
      {grouperParEtagere && (
        <div className="px-4 py-1.5 text-[11px] text-gray-400 border-b border-gray-100 bg-white">
          💡 Glissez un livre d'une étagère à l'autre, ou survolez un titre pour le renommer — tout est appliqué direct dans BookStack.
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
              const cible = survol === g.nom
              return (
                <section key={g.nom}
                  onDragOver={e => { if (drag) { e.preventDefault(); setSurvol(g.nom) } }}
                  onDragLeave={() => setSurvol(s => (s === g.nom ? null : s))}
                  onDrop={() => deposer(g.shelfId, g.nom)}
                  className={cible ? 'rounded-lg ring-2 ring-blue-400 ring-offset-2' : ''}>
                  <div className="flex items-center gap-1.5 mb-2.5 group/etagere">
                    <button type="button" onClick={() => basculerRepli(g.nom)} aria-expanded={!replie}
                      className="text-xs font-semibold uppercase tracking-wide text-gray-500 hover:text-gray-700 flex items-center gap-1.5">
                      {replie ? <ChevronRight size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
                      <Library size={14} className="text-blue-500" /> {g.nom}
                      <span className="text-gray-300 font-normal normal-case">· {g.livres.length}</span>
                    </button>
                    {g.shelfId !== null && (
                      <button type="button" onClick={() => renommerEtagere(g)} title="Renommer l'étagère"
                        className="opacity-0 group-hover/etagere:opacity-100 p-0.5 text-gray-400 hover:text-blue-600 transition-opacity">
                        <Pencil size={12} />
                      </button>
                    )}
                  </div>
                  {!replie && (
                    <GrilleLivres livres={g.livres} fromShelfId={g.shelfId} dragActif={!!drag}
                      onDragStart={(bookId) => setDrag({ bookId, fromShelfId: g.shelfId })}
                      onDragEnd={() => { setDrag(null); setSurvol(null) }}
                      onRenommer={renommerLivre} />
                  )}
                </section>
              )
            })}
          </div>
        ) : (
          <GrilleLivres livres={filtres} fromShelfId={null} dragActif={false}
            onDragStart={() => {}} onDragEnd={() => {}} onRenommer={renommerLivre} />
        )}
      </div>
    </div>
  )
}

interface GrilleProps {
  livres: WikiBook[]
  fromShelfId: number | null
  dragActif: boolean
  onDragStart: (bookId: number) => void
  onDragEnd: () => void
  onRenommer: (b: WikiBook) => void
}

/** Grille de cartes de livres — draggable + bouton renommer (✏️ au survol). */
function GrilleLivres({ livres, dragActif, onDragStart, onDragEnd, onRenommer }: GrilleProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
      {livres.map(b => (
        <div key={b.id} className="relative group/livre">
          <Link to={`/wiki/livres/${b.id}`}
            draggable
            onDragStart={e => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(b.id)); onDragStart(b.id) }}
            onDragEnd={onDragEnd}
            className={`bg-white border border-gray-200 rounded-lg overflow-hidden hover:border-blue-300 hover:shadow-sm transition-all flex flex-col ${dragActif ? 'cursor-grabbing' : ''}`}>
            <div className="aspect-[3/4] bg-gray-100 flex items-center justify-center overflow-hidden">
              {b.cover_url
                ? <img src={b.cover_url} alt="" loading="lazy" className="w-full h-full object-cover" draggable={false} />
                : <BookOpen size={40} className="text-gray-300" />}
            </div>
            <div className="p-2.5 flex-1 flex flex-col gap-1">
              <span className="text-sm font-medium text-gray-800 leading-tight line-clamp-2">{b.name}</span>
              {b.description && <span className="text-[11px] text-gray-400 line-clamp-2">{b.description}</span>}
            </div>
          </Link>
          {/* Renommer — n'interfère pas avec le clic d'ouverture (bouton superposé). */}
          <button type="button" onClick={() => onRenommer(b)} title="Renommer le livre"
            className="absolute top-1.5 right-1.5 opacity-0 group-hover/livre:opacity-100 p-1 rounded-md bg-white/90 border border-gray-200 text-gray-500 hover:text-blue-600 shadow-sm transition-opacity">
            <Pencil size={12} />
          </button>
        </div>
      ))}
    </div>
  )
}
