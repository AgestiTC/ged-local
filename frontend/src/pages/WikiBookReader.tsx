/**
 * WikiBookReader — lecture intégrée d'un livre BookStack.
 * Sommaire (chapitres/pages) à gauche + rendu HTML de la page à droite + lien BookStack.
 */
import { useEffect, useState } from 'react'
import DOMPurify from 'dompurify'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ChevronRight, ExternalLink, FileText, Loader2, List, PencilLine, Send, X } from 'lucide-react'
import { extractApiError, wikiApi, type WikiBookDetail, type WikiPageContent } from '../api'
import { useToast } from '../components/common/Toast'

export default function WikiBookReader() {
  const { id } = useParams()
  const bookId = Number(id)
  const [book, setBook] = useState<WikiBookDetail | null>(null)
  const [page, setPage] = useState<WikiPageContent | null>(null)
  const [loadingPage, setLoadingPage] = useState(false)
  const [tocOpen, setTocOpen] = useState(false)   // sommaire en tiroir sur mobile (< md)
  // Proposer une modification d'une page du cockpit (16/11/2026) : la source est le `.md` du projet,
  // pas BookStack (le dépôt suivant écraserait une retouche faite là-bas).
  const [edition, setEdition] = useState<{ avant: string; texte: string; commentaire: string; converti: boolean } | null>(null)
  const [envoi, setEnvoi] = useState(false)
  const toast = useToast()

  useEffect(() => { wikiApi.book(bookId).then(setBook).catch(() => setBook(null)) }, [bookId])

  const ouvrirPage = (pid: number) => {
    setEdition(null)
    setLoadingPage(true)
    wikiApi.page(pid).then(setPage).catch(() => setPage(null)).finally(() => setLoadingPage(false))
  }

  const ouvrirEdition = async () => {
    if (!page) return
    try {
      const s = await wikiApi.source(page.id)
      setEdition({ avant: s.markdown, texte: s.markdown, commentaire: '', converti: s.converti })
    } catch (e) { toast.error(extractApiError(e, 'Source de la page illisible')) }
  }

  const envoyerProposition = async () => {
    if (!page || !edition) return
    setEnvoi(true)
    try {
      const r = await wikiApi.proposer(page.id, edition.texte, edition.commentaire)
      toast.success(r.statut === 'transmise'
        ? `Proposition envoyée au projet « ${r.projet} » : elle sera relue puis appliquée depuis le cockpit.`
        : 'Proposition envoyée : un administrateur la relira avant de l\'appliquer.')
      setEdition(null)
    } catch (e) { toast.error(extractApiError(e, 'Proposition impossible')) } finally { setEnvoi(false) }
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
          ) : page && edition ? (
            <div className="max-w-3xl bg-white rounded-lg border border-gray-200 p-4 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-gray-700 truncate">Proposer une modification — {page.name}</h2>
                <button type="button" onClick={() => setEdition(null)} title="Annuler"
                  className="text-gray-400 hover:text-gray-700"><X size={16} /></button>
              </div>
              <p className="text-xs text-gray-500">
                {page.origine === 'cockpit'
                  ? <>Cette page vient du projet <strong>{page.projet}</strong> (<code>{page.cle}.md</code>). Votre texte est
                    envoyé au projet, avec votre nom, puis relu et appliqué depuis le cockpit.</>
                  : page.origine === 'projet'
                    ? <>Cette page est publiée par le projet <strong>{page.projet}</strong>. Votre proposition, avec votre nom,
                      sera reportée dans le projet par un administrateur.</>
                    : <>Votre texte n'est pas publié tel quel : il est enregistré avec votre nom, puis relu et appliqué
                      par un administrateur.</>}
              </p>
              {edition.converti && (
                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                  Cette page a été écrite avec l'éditeur visuel : elle est montrée ici en Markdown. Une mise en page
                  élaborée (couleurs, tableaux fusionnés) peut être simplifiée si la proposition est appliquée.
                </p>
              )}
              <textarea value={edition.texte} rows={20} aria-label="Texte proposé (Markdown)"
                onChange={e => setEdition(ed => ed && { ...ed, texte: e.target.value })}
                className="w-full text-sm font-mono border border-gray-200 rounded-md p-2 focus:outline-none focus:ring-1 focus:ring-blue-400" />
              <input type="text" value={edition.commentaire} maxLength={2000} placeholder="Pourquoi ce changement ? (facultatif)"
                onChange={e => setEdition(ed => ed && { ...ed, commentaire: e.target.value })}
                className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5" />
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setEdition(null)}
                  className="text-sm px-3 py-1.5 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50">Annuler</button>
                <button type="button" disabled={envoi || edition.texte.trim() === edition.avant.trim()} onClick={() => void envoyerProposition()}
                  className="text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5">
                  <Send size={14} /> {envoi ? 'Envoi…' : 'Envoyer la proposition'}</button>
              </div>
            </div>
          ) : page ? (
            <div className="max-w-3xl">
              {page.origine && (
                <div className="flex justify-end mb-2">
                  <button type="button" onClick={() => void ouvrirEdition()}
                    title="Proposer une correction : elle est relue avant d'être appliquée (votre nom est gardé)"
                    className="text-xs flex items-center gap-1 px-3 py-1.5 rounded-md border border-gray-200 bg-white text-gray-600 hover:bg-gray-50">
                    <PencilLine size={13} /> Proposer une modification
                  </button>
                </div>
              )}
              {/* Contenu du wiki, NETTOYÉ avant rendu : BookStack est multi-éditeurs, et un script
                 glissé dans une page s'exécuterait ici avec les droits de Matothèque (même
                 origine que son API). Défense en profondeur — audit du 28/09/2026, M2. */}
              <article className="wiki-content bg-white rounded-lg border border-gray-200 p-6"
                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(page.html) }} />
            </div>
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
