/**
 * WikiBookReader — lecture intégrée d'un livre BookStack.
 * Sommaire (chapitres/pages) à gauche + rendu HTML de la page à droite + lien BookStack.
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ChevronRight, ExternalLink, FileText, Loader2 } from 'lucide-react'
import { wikiApi, type WikiBookDetail, type WikiPageContent } from '../api'

export default function WikiBookReader() {
  const { id } = useParams()
  const bookId = Number(id)
  const [book, setBook] = useState<WikiBookDetail | null>(null)
  const [page, setPage] = useState<WikiPageContent | null>(null)
  const [loadingPage, setLoadingPage] = useState(false)

  useEffect(() => { wikiApi.book(bookId).then(setBook).catch(() => setBook(null)) }, [bookId])

  const ouvrirPage = (pid: number) => {
    setLoadingPage(true)
    wikiApi.page(pid).then(setPage).catch(() => setPage(null)).finally(() => setLoadingPage(false))
  }

  const lienPage = (pid: number, nom: string, indent = false) => (
    <button key={`p${pid}`} type="button" onClick={() => ouvrirPage(pid)}
      className={`w-full text-left text-sm px-2 py-1.5 rounded flex items-center gap-1.5 ${indent ? 'pl-5' : ''} ${
        page?.id === pid ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-50'}`}>
      <FileText size={13} className="shrink-0" /> <span className="truncate">{nom}</span>
    </button>
  )

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b border-gray-200 bg-white flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Link to="/wiki/livres" className="text-gray-400 hover:text-gray-600 shrink-0"><ArrowLeft size={18} /></Link>
          <h1 className="text-base font-bold text-gray-800 truncate">{book?.name ?? 'Livre'}</h1>
        </div>
        {book?.url && (
          <a href={book.url} target="_blank" rel="noopener noreferrer"
            className="text-xs flex items-center gap-1 px-3 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 shrink-0">
            Ouvrir dans BookStack <ExternalLink size={12} />
          </a>
        )}
      </div>

      <div className="flex-1 flex min-h-0">
        <aside className="w-64 shrink-0 border-r border-gray-200 bg-white overflow-y-auto p-2">
          {!book ? (
            <div className="flex justify-center py-6"><Loader2 size={18} className="animate-spin text-gray-400" /></div>
          ) : book.contents.length === 0 ? (
            <p className="text-xs text-gray-400 p-2">Livre vide.</p>
          ) : book.contents.map(item =>
            item.type === 'page'
              ? lienPage(item.id, item.name)
              : (
                <div key={`c${item.id}`} className="mt-1">
                  <div className="text-[11px] uppercase tracking-wide text-gray-400 px-2 py-1 flex items-center gap-1">
                    <ChevronRight size={11} /> {item.name}
                  </div>
                  {(item.pages ?? []).map(pg => lienPage(pg.id, pg.name, true))}
                </div>
              ),
          )}
        </aside>

        <div className="flex-1 overflow-y-auto p-6 bg-gray-50">
          {loadingPage ? (
            <div className="flex justify-center py-16"><Loader2 size={22} className="animate-spin text-gray-400" /></div>
          ) : page ? (
            /* Contenu du wiki interne (confiance) — rendu HTML. */
            <article className="wiki-content max-w-3xl bg-white rounded-lg border border-gray-200 p-6"
              dangerouslySetInnerHTML={{ __html: page.html }} />
          ) : (
            <p className="text-gray-400 text-center py-16">
              {book?.description || 'Choisis une page dans le sommaire pour la lire.'}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
