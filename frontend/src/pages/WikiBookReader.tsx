/**
 * WikiBookReader — lecture intégrée d'un livre BookStack.
 * Sommaire (chapitres/pages) à gauche + rendu HTML de la page à droite + lien BookStack.
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ChevronRight, ExternalLink, FileText, Loader2, List } from 'lucide-react'
import { wikiApi, type WikiBookDetail, type WikiPageContent } from '../api'

export default function WikiBookReader() {
  const { id } = useParams()
  const bookId = Number(id)
  const [book, setBook] = useState<WikiBookDetail | null>(null)
  const [page, setPage] = useState<WikiPageContent | null>(null)
  const [loadingPage, setLoadingPage] = useState(false)
  const [tocOpen, setTocOpen] = useState(false)   // sommaire en tiroir sur mobile (< md)

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

  // Sommaire du livre — partagé entre l'aside bureau et le tiroir mobile.
  const sommaire = !book ? (
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
  )

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b border-gray-200 bg-white flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Link to="/wiki/livres" className="text-gray-400 hover:text-gray-600 shrink-0"><ArrowLeft size={18} /></Link>
          <button type="button" onClick={() => setTocOpen(true)} title="Sommaire"
            className="md:hidden text-gray-500 hover:text-gray-700 shrink-0"><List size={18} /></button>
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
        {/* Sommaire — fixe sur bureau (≥ md), en tiroir sur mobile. */}
        <aside className="hidden md:block w-64 shrink-0 border-r border-gray-200 bg-white overflow-y-auto p-2">
          {sommaire}
        </aside>
        {tocOpen && (
          <div className="fixed inset-0 z-40 md:hidden" onClick={() => setTocOpen(false)}>
            <div className="absolute inset-0 bg-black/40" />
            <aside className="absolute left-0 top-0 h-full w-72 max-w-[85%] bg-white shadow-xl overflow-y-auto p-2"
              onClick={e => { if ((e.target as HTMLElement).closest('a,button')) setTocOpen(false) }}>
              <div className="flex items-center justify-between px-2 py-1 mb-1">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Sommaire</span>
                <button type="button" onClick={() => setTocOpen(false)} className="text-gray-400 hover:text-gray-700 text-sm">✕</button>
              </div>
              {sommaire}
            </aside>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4 sm:p-6 bg-gray-50">
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
