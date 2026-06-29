/**
 * PublishBookStackModal — Publier un contenu en page (tuto) sur le wiki BookStack
 * ==============================================================================
 * Réutilisable : on lui passe soit un `markdown` direct, soit un `documentId`
 * (le backend publiera alors le texte extrait du document).
 */
import { useEffect, useMemo, useState } from 'react'
import { BookOpen, ExternalLink, Send, X } from 'lucide-react'
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
  const [cible, setCible] = useState('')          // ex: "book:118" | "chapter:42"
  const [publishing, setPublishing] = useState(false)
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

  // Options groupées : chapitres rattachés à leur livre.
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

  const handlePublish = async () => {
    if (!titre.trim()) { toast.error('Indiquez un titre.'); return }
    if (!cible) { toast.error('Choisissez un livre ou un chapitre cible.'); return }
    const [type, id] = cible.split(':')
    setPublishing(true)
    try {
      const res = await bookstackApi.publish({
        titre: titre.trim(),
        markdown,
        document_id: markdown ? undefined : documentId,
        book_id: type === 'book' ? Number(id) : undefined,
        chapter_id: type === 'chapter' ? Number(id) : undefined,
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
              <label className="block text-xs text-gray-500 mb-1">Titre de la page *</label>
              <input
                type="text" value={titre} onChange={e => setTitre(e.target.value)}
                placeholder="Ex : Installation de Vaultwarden"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-purple-400"
              />
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-1">Emplacement (livre ou chapitre) *</label>
              {loadingTargets ? (
                <div className="py-2"><LoadingSpinner size={16} label="Chargement des livres…" /></div>
              ) : (
                <select
                  value={cible} onChange={e => setCible(e.target.value)}
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-1 focus:ring-purple-400"
                >
                  <option value="">— Choisir une cible —</option>
                  {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              )}
            </div>

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
