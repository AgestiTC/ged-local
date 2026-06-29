/**
 * PublishBookStackModal — Publier un contenu en page (tuto) sur le wiki BookStack
 * ==============================================================================
 * Réutilisable : on lui passe soit un `markdown` direct, soit un `documentId`
 * (le backend publiera alors le texte extrait du document).
 *
 * Lot 1a : la cible peut être un livre/chapitre **existant** OU **créé à la volée**
 * (+ bouton « Proposer » qui pré-remplit titre et emplacement via le LLM).
 */
import { useEffect, useMemo, useState } from 'react'
import { BookOpen, ExternalLink, Send, Sparkles, X } from 'lucide-react'
import { bookstackApi, type BookStackTargets } from '../../api'
import { useToast } from './Toast'
import LoadingSpinner from './LoadingSpinner'

interface PublishBookStackModalProps {
  isOpen: boolean
  onClose: () => void
  defaultTitle?: string
  /** Contenu Markdown à publier (prioritaire sur documentId) */
  markdown?: string
  /** Alternative : publier le texte extrait d'un document indexé */
  documentId?: string
  onPublished?: (pageUrl: string) => void
}

// Valeurs spéciales du sélecteur de cible (au-delà de "book:id" / "chapter:id").
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

export default function PublishBookStackModal({
  isOpen, onClose, defaultTitle = '', markdown, documentId, onPublished,
}: PublishBookStackModalProps) {
  const toast = useToast()
  const [titre, setTitre] = useState(defaultTitle)
  const [targets, setTargets] = useState<BookStackTargets | null>(null)
  const [loadingTargets, setLoadingTargets] = useState(false)
  const [cible, setCible] = useState('')          // "book:118" | "chapter:42" | NEW_BOOK | NEW_CHAPTER
  const [newBookName, setNewBookName] = useState('')
  const [newChapterName, setNewChapterName] = useState('')
  const [parentBook, setParentBook] = useState('') // pour NEW_CHAPTER : "book:118" | NEW_BOOK
  const [publishing, setPublishing] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [resultUrl, setResultUrl] = useState<string | null>(null)

  useEffect(() => { setTitre(defaultTitle) }, [defaultTitle])

  useEffect(() => {
    if (!isOpen) return
    setResultUrl(null)
    setLoadingTargets(true)
    bookstackApi.targets()
      .then(t => setTargets(t))
      .catch(e => toast.error(extractApiError(e)))
      .finally(() => setLoadingTargets(false))
  }, [isOpen, toast])

  // Options existantes : chapitres rattachés à leur livre.
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

  if (!isOpen) return null

  const hasContent = Boolean(markdown || documentId)

  const handleSuggest = async () => {
    setSuggesting(true)
    try {
      const s = await bookstackApi.suggest({
        markdown,
        document_id: markdown ? undefined : documentId,
      })
      if (s.titre) setTitre(s.titre)
      if (s.chapitre) {
        // Suggestion d'un chapitre → mode "nouveau chapitre".
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

  // Construit la cible du payload de publication ; renvoie null si invalide.
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
      else return null  // chapitre sans livre parent
      return t
    }
    return null
  }

  const handlePublish = async () => {
    if (!titre.trim()) { toast.error('Indiquez un titre.'); return }
    const target = buildTarget()
    if (!target) { toast.error('Précisez un emplacement valide (livre/chapitre).'); return }
    setPublishing(true)
    try {
      const res = await bookstackApi.publish({
        titre: titre.trim(),
        markdown,
        document_id: markdown ? undefined : documentId,
        ...target,
      })
      setResultUrl(res.page_url)
      toast.success('Tuto publié sur le wiki')
      onPublished?.(res.page_url)
    } catch (e) {
      toast.error(extractApiError(e))
    } finally {
      setPublishing(false)
    }
  }

  const inputCls = 'w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-purple-400'
  const selectCls = inputCls + ' bg-white'

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-800 flex items-center gap-2">
            <BookOpen size={18} className="text-purple-600" /> Publier sur le wiki
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>

        {resultUrl ? (
          <div className="space-y-4">
            <p className="text-sm text-gray-600">La page a été créée dans le wiki.</p>
            <a
              href={resultUrl} target="_blank" rel="noreferrer"
              className="flex items-center gap-2 text-sm text-purple-700 hover:underline break-all"
            >
              <ExternalLink size={14} className="shrink-0" /> {resultUrl}
            </a>
            <div className="flex justify-end">
              <button onClick={onClose} className="px-4 py-2 text-sm bg-gray-100 rounded-lg hover:bg-gray-200">Fermer</button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs text-gray-500">Titre de la page *</label>
                <button
                  type="button"
                  onClick={handleSuggest}
                  disabled={suggesting || !hasContent}
                  title="Proposer un titre et un emplacement (IA)"
                  className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 disabled:opacity-40"
                >
                  {suggesting ? <LoadingSpinner size={12} /> : <Sparkles size={12} />} Proposer
                </button>
              </div>
              <input
                type="text" value={titre} onChange={e => setTitre(e.target.value)}
                placeholder="Ex : Installation de Vaultwarden"
                className={inputCls}
              />
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-1">Emplacement (livre ou chapitre) *</label>
              {loadingTargets ? (
                <div className="py-2"><LoadingSpinner size={16} label="Chargement des livres…" /></div>
              ) : (
                <select aria-label="Emplacement de publication" value={cible} onChange={e => setCible(e.target.value)} className={selectCls}>
                  <option value="">— Choisir une cible —</option>
                  <option value={NEW_BOOK}>➕ Nouveau livre…</option>
                  <option value={NEW_CHAPTER}>➕ Nouveau chapitre…</option>
                  {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              )}
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
                    {targets?.books.map(b => (
                      <option key={b.id} value={`book:${b.id}`}>📘 {b.name}</option>
                    ))}
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

            <p className="text-xs text-gray-400">
              {markdown
                ? 'Le contenu généré sera publié tel quel (Markdown).'
                : 'Le texte extrait du document sera publié comme contenu de la page.'}
            </p>

            <div className="flex gap-2 justify-end pt-1">
              <button onClick={onClose} disabled={publishing} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">
                Annuler
              </button>
              <button
                onClick={handlePublish} disabled={publishing || loadingTargets}
                className="flex items-center gap-1.5 px-4 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50"
              >
                {publishing ? <LoadingSpinner size={14} /> : <Send size={14} />}
                {publishing ? 'Publication…' : 'Publier'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
