/**
 * WikiBooksPage — « Wiki › Liste des livres ».
 * Grille des livres BookStack avec couverture en miniature ; clic → lecture intégrée.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, Loader2, RefreshCw, Search } from 'lucide-react'
import { wikiApi, type WikiBook } from '../api'

export default function WikiBooksPage() {
  const [books, setBooks] = useState<WikiBook[]>([])
  const [configured, setConfigured] = useState(true)
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [indexing, setIndexing] = useState(false)
  const [indexMsg, setIndexMsg] = useState<string | null>(null)

  const lancerIndexation = () => {
    setIndexing(true); setIndexMsg(null)
    wikiApi.index()
      .then(() => setIndexMsg('Indexation lancée — les pages apparaîtront dans la GED sous la catégorie « livre » (tâche en arrière-plan).'))
      .catch(() => setIndexMsg("Échec du lancement de l'indexation."))
      .finally(() => setIndexing(false))
  }

  useEffect(() => {
    wikiApi.books()
      .then(r => { setConfigured(r.configured); setBooks(r.books) })
      .catch(() => setConfigured(false))
      .finally(() => setLoading(false))
  }, [])

  const filtres = books.filter(b =>
    b.name.toLowerCase().includes(q.toLowerCase()) ||
    b.description.toLowerCase().includes(q.toLowerCase()),
  )

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b border-gray-200 bg-white flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-base font-bold text-gray-800 flex items-center gap-2">
          <BookOpen size={18} className="text-blue-600" /> Wiki — Liste des livres
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

      <div className="flex-1 overflow-y-auto p-4 bg-gray-50">
        {loading ? (
          <div className="flex justify-center py-16"><Loader2 size={22} className="animate-spin text-gray-400" /></div>
        ) : !configured ? (
          <p className="text-sm text-gray-400 text-center py-16">
            BookStack n'est pas configuré — renseigne l'URL et le token dans <strong>Paramètres → BookStack</strong>.
          </p>
        ) : filtres.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-16">Aucun livre.</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {filtres.map(b => (
              <Link key={b.id} to={`/wiki/livres/${b.id}`}
                className="bg-white border border-gray-200 rounded-lg overflow-hidden hover:border-blue-300 hover:shadow-sm transition-all flex flex-col">
                <div className="aspect-[3/4] bg-gray-100 flex items-center justify-center overflow-hidden">
                  {b.cover_url
                    ? <img src={b.cover_url} alt="" loading="lazy" className="w-full h-full object-cover" />
                    : <BookOpen size={40} className="text-gray-300" />}
                </div>
                <div className="p-2.5 flex-1 flex flex-col gap-1">
                  <span className="text-sm font-medium text-gray-800 leading-tight line-clamp-2">{b.name}</span>
                  {b.description && <span className="text-[11px] text-gray-400 line-clamp-2">{b.description}</span>}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
