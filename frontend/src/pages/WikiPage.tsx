/**
 * Page Wiki — Matothèque
 * ======================
 * Module dédié à la création de documentation sur le wiki BookStack.
 *
 * - Colonne gauche : arborescence du wiki (livres → chapitres) en lecture.
 * - Colonne droite : composer un tuto (titre + Markdown), choisir OU créer
 *   l'emplacement (livre/chapitre), proposer titre+emplacement via le LLM,
 *   puis publier. S'appuie sur le moteur du Lot 1a (bookstackApi).
 */
import { useEffect, useMemo, useState } from 'react'
import { BookOpen, ChevronRight, ExternalLink, RefreshCw, Send, Sparkles } from 'lucide-react'
import { bookstackApi, type BookStackTargets } from '../api'
import { useToast } from '../components/common/Toast'
import LoadingSpinner from '../components/common/LoadingSpinner'

const NEW_BOOK = '__new_book__'
const NEW_CHAPTER = '__new_chapter__'

function extractApiError(e: unknown): string {
  if (e && typeof e === 'object') {
    const ax = e as { response?: { data?: { detail?: string } }; message?: string }
    if (ax.response?.data?.detail) return ax.response.data.detail
    if (ax.message) return ax.message
  }
  return 'Erreur inconnue'
}

export default function WikiPage() {
  const toast = useToast()
  const [targets, setTargets] = useState<BookStackTargets | null>(null)
  const [loadingTargets, setLoadingTargets] = useState(false)
  const [configError, setConfigError] = useState<string | null>(null)

  const [titre, setTitre] = useState('')
  const [contenu, setContenu] = useState('')
  const [cible, setCible] = useState('')          // "book:id" | "chapter:id" | NEW_BOOK | NEW_CHAPTER
  const [newBookName, setNewBookName] = useState('')
  const [newChapterName, setNewChapterName] = useState('')
  const [parentBook, setParentBook] = useState('') // pour NEW_CHAPTER
  const [publishing, setPublishing] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [lastUrl, setLastUrl] = useState<string | null>(null)

  const loadTargets = () => {
    setLoadingTargets(true)
    setConfigError(null)
    bookstackApi.targets()
      .then(t => setTargets(t))
      .catch(e => { setConfigError(extractApiError(e)); setTargets(null) })
      .finally(() => setLoadingTargets(false))
  }

  useEffect(loadTargets, [])

  const options = useMemo(() => {
    if (!targets) return []
    const opts: Array<{ value: string; label: string }> = []
    for (const b of targets.books) {
      opts.push({ value: `book:${b.id}`, label: `📘 ${b.name}` })
      for (const c of targets.chapters.filter(ch => ch.book_id === b.id)) {
        opts.push({ value: `chapter:${c.id}`, label: `   └ 📑 ${c.name}` })
      }
    }
    return opts
  }, [targets])

  const handleSuggest = async () => {
    if (!contenu.trim()) { toast.error('Rédigez d’abord le contenu à analyser.'); return }
    setSuggesting(true)
    try {
      const s = await bookstackApi.suggest({ markdown: contenu })
      if (s.titre) setTitre(s.titre)
      if (s.chapitre) {
        setCible(NEW_CHAPTER)
        setNewChapterName(s.chapitre)
        if (s.book_id) setParentBook(`book:${s.book_id}`)
        else if (s.nouveau_livre) { setParentBook(NEW_BOOK); setNewBookName(s.nouveau_livre) }
      } else if (s.book_id) {
        setCible(`book:${s.book_id}`)
      } else if (s.nouveau_livre) {
        setCible(NEW_BOOK)
        setNewBookName(s.nouveau_livre)
      }
      toast.success(s.raison ? `Proposition : ${s.raison}` : 'Proposition appliquée')
    } catch (e) {
      toast.error(extractApiError(e))
    } finally {
      setSuggesting(false)
    }
  }

  const buildTarget = (): Partial<{ book_id: number; chapter_id: number; new_book: string; new_chapter: string }> | null => {
    if (cible.startsWith('book:')) return { book_id: Number(cible.slice(5)) }
    if (cible.startsWith('chapter:')) return { chapter_id: Number(cible.slice(8)) }
    if (cible === NEW_BOOK) {
      if (!newBookName.trim()) return null
      return { new_book: newBookName.trim() }
    }
    if (cible === NEW_CHAPTER) {
      if (!newChapterName.trim()) return null
      const t: Record<string, string | number> = { new_chapter: newChapterName.trim() }
      if (parentBook.startsWith('book:')) t.book_id = Number(parentBook.slice(5))
      else if (parentBook === NEW_BOOK && newBookName.trim()) t.new_book = newBookName.trim()
      else return null
      return t
    }
    return null
  }

  const handlePublish = async () => {
    if (!titre.trim()) { toast.error('Indiquez un titre.'); return }
    if (!contenu.trim()) { toast.error('Le contenu est vide.'); return }
    const target = buildTarget()
    if (!target) { toast.error('Précisez un emplacement valide (livre/chapitre).'); return }
    setPublishing(true)
    try {
      const res = await bookstackApi.publish({ titre: titre.trim(), markdown: contenu, ...target })
      setLastUrl(res.page_url)
      toast.success('Tuto publié sur le wiki')
      loadTargets()  // un nouveau livre/chapitre apparaît dans l'arbre
    } catch (e) {
      toast.error(extractApiError(e))
    } finally {
      setPublishing(false)
    }
  }

  const inputCls = 'w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-purple-400'
  const selectCls = inputCls + ' bg-white'

  return (
    <div className="flex h-full">
      {/* ─── Arborescence du wiki ─── */}
      <aside className="w-72 border-r border-gray-200 bg-gray-50 flex flex-col shrink-0">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <BookOpen size={15} className="text-purple-600" /> Wiki
          </h2>
          <button type="button" onClick={loadTargets} title="Rafraîchir" className="text-gray-400 hover:text-gray-600">
            <RefreshCw size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 text-sm">
          {loadingTargets ? (
            <div className="py-4"><LoadingSpinner size={16} label="Chargement…" /></div>
          ) : configError ? (
            <p className="text-xs text-amber-600 p-2">{configError}</p>
          ) : targets && targets.books.length > 0 ? (
            <ul className="space-y-0.5">
              {targets.books.map(b => (
                <li key={b.id}>
                  <div className="flex items-center gap-1.5 px-2 py-1 text-gray-700 font-medium">
                    <span>📘</span> {b.name}
                  </div>
                  {targets.chapters.filter(c => c.book_id === b.id).map(c => (
                    <div key={c.id} className="flex items-center gap-1 pl-6 py-0.5 text-gray-500 text-xs">
                      <ChevronRight size={11} /> 📑 {c.name}
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-gray-400 p-2">Aucun livre. Créez-en un en publiant un premier tuto.</p>
          )}
        </div>
      </aside>

      {/* ─── Composer ─── */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto p-6 space-y-5">
          <div>
            <h1 className="text-lg font-semibold text-gray-800">Créer un tuto</h1>
            <p className="text-sm text-gray-500">Rédigez en Markdown, choisissez ou créez l’emplacement, puis publiez sur le wiki.</p>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs text-gray-500">Titre de la page *</label>
              <button
                type="button" onClick={handleSuggest} disabled={suggesting || !contenu.trim()}
                title="Proposer un titre et un emplacement (IA)"
                className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 disabled:opacity-40"
              >
                {suggesting ? <LoadingSpinner size={12} /> : <Sparkles size={12} />} Proposer
              </button>
            </div>
            <input
              type="text" value={titre} onChange={e => setTitre(e.target.value)}
              placeholder="Ex : Installation de Vaultwarden" className={inputCls}
            />
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Contenu (Markdown) *</label>
            <textarea
              value={contenu} onChange={e => setContenu(e.target.value)}
              placeholder="# Titre&#10;&#10;Décrivez la procédure…"
              className={inputCls + ' font-mono min-h-[280px] resize-y'}
            />
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Emplacement (livre ou chapitre) *</label>
            <select aria-label="Emplacement de publication" value={cible} onChange={e => setCible(e.target.value)} className={selectCls}>
              <option value="">— Choisir une cible —</option>
              <option value={NEW_BOOK}>➕ Nouveau livre…</option>
              <option value={NEW_CHAPTER}>➕ Nouveau chapitre…</option>
              {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          {cible === NEW_BOOK && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Nom du nouveau livre *</label>
              <input
                type="text" value={newBookName} onChange={e => setNewBookName(e.target.value)}
                placeholder="Ex : Infrastructure réseau" className={inputCls}
              />
            </div>
          )}

          {cible === NEW_CHAPTER && (
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Nom du nouveau chapitre *</label>
                <input
                  type="text" value={newChapterName} onChange={e => setNewChapterName(e.target.value)}
                  placeholder="Ex : Sauvegardes" className={inputCls}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Dans le livre *</label>
                <select aria-label="Livre parent du nouveau chapitre" value={parentBook} onChange={e => setParentBook(e.target.value)} className={selectCls}>
                  <option value="">— Choisir un livre —</option>
                  <option value={NEW_BOOK}>➕ Nouveau livre…</option>
                  {targets?.books.map(b => <option key={b.id} value={`book:${b.id}`}>📘 {b.name}</option>)}
                </select>
              </div>
              {parentBook === NEW_BOOK && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Nom du nouveau livre *</label>
                  <input
                    type="text" value={newBookName} onChange={e => setNewBookName(e.target.value)}
                    placeholder="Ex : Infrastructure réseau" className={inputCls}
                  />
                </div>
              )}
            </div>
          )}

          {lastUrl && (
            <a
              href={lastUrl} target="_blank" rel="noreferrer"
              className="flex items-center gap-2 text-sm text-purple-700 hover:underline break-all"
            >
              <ExternalLink size={14} className="shrink-0" /> {lastUrl}
            </a>
          )}

          <div className="flex justify-end pt-1">
            <button
              type="button" onClick={handlePublish} disabled={publishing || loadingTargets}
              className="flex items-center gap-1.5 px-5 py-2.5 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50"
            >
              {publishing ? <LoadingSpinner size={14} /> : <Send size={14} />}
              {publishing ? 'Publication…' : 'Publier sur le wiki'}
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
