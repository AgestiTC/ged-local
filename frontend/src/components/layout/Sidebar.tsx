/**
 * Sidebar — Navigation principale Matothèque
 * Menus DYNAMIQUES : un item n'apparaît que si le service correspondant est configuré
 * (BookStack → Publier + WIKI ; token HuggingFace → HuggingFace ; liens → Administration).
 * Pas de menu parasite.
 */
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { BookOpen, Boxes, ChevronDown, Copy, ExternalLink, LayoutGrid, Library, PenSquare, FolderOpen, FolderTree, Settings, Upload } from 'lucide-react'
import { systemApi } from '../../api'

export default function Sidebar() {
  const location = useLocation()
  const [version, setVersion] = useState<string | null>(null)
  const [bookstackUrl, setBookstackUrl] = useState('')
  const [hfConfig, setHfConfig] = useState(false)
  const [adminCount, setAdminCount] = useState(0)
  // État déplié/replié du menu Wiki, mémorisé entre les visites.
  const [wikiOpen, setWikiOpen] = useState(() => localStorage.getItem('mtq_wiki_open') !== 'false')

  useEffect(() => { systemApi.version().then(v => setVersion(v.version)).catch(() => {}) }, [])
  useEffect(() => {
    systemApi.getConfig().then(c => {
      setBookstackUrl(c.bookstack_url?.valeur ?? '')
      setHfConfig(!!(c.huggingface_token?.defini || c.huggingface_token?.valeur))
      try { setAdminCount((JSON.parse(c.admin_links?.valeur || '[]') as unknown[]).length) } catch { setAdminCount(0) }
    }).catch(() => {})
  }, [])

  // Items internes conditionnels (pas de menu inutile si non configuré).
  const items = [
    { to: '/', label: 'Créer', Icon: PenSquare, show: true },
    { to: '/ged', label: 'GED', Icon: FolderOpen, show: true },
    { to: '/doublons', label: 'Doublons', Icon: Copy, show: true },
    { to: '/reorganiser', label: 'Réorganiser', Icon: FolderTree, show: true },
    { to: '/huggingface', label: 'HuggingFace', Icon: Boxes, show: hfConfig },
    { to: '/admin', label: 'Administration', Icon: LayoutGrid, show: adminCount > 0 },
  ].filter(i => i.show)

  const cls = (active: boolean) =>
    `flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
      active ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-800 hover:text-white'
    }`

  return (
    <nav className="w-52 bg-gray-900 text-white flex flex-col shrink-0">
      <div className="p-4 border-b border-gray-700">
        <h1 className="font-bold text-base tracking-tight">Matothèque</h1>
        <p className="text-xs text-gray-500 mt-0.5">{version ? `v${version} — ` : ''}100% local</p>
      </div>
      <ul className="flex-1 p-2 space-y-0.5">
        {items.map(({ to, label, Icon }) => (
          <li key={to}>
            <Link to={to} className={cls(location.pathname === to)}>
              <Icon size={15} />
              <span>{label}</span>
            </Link>
          </li>
        ))}

        {/* Wiki — groupe dépliable : « Publier » (page interne) + « Ouvrir WIKI » (BookStack
            externe). Affiché seulement si BookStack est configuré. */}
        {bookstackUrl && (
          <li>
            <button
              type="button"
              onClick={() => setWikiOpen(o => { localStorage.setItem('mtq_wiki_open', String(!o)); return !o })}
              aria-expanded={wikiOpen}
              title={wikiOpen ? 'Replier le menu Wiki' : 'Déplier le menu Wiki'}
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors">
              <BookOpen size={15} />
              <span className="flex-1 text-left">Wiki</span>
              <ChevronDown size={14} className={`text-gray-500 transition-transform ${wikiOpen ? '' : '-rotate-90'}`} />
            </button>
            {wikiOpen && (
              <ul className="mt-0.5 ml-4 pl-2 border-l border-gray-800 space-y-0.5">
                <li>
                  <Link to="/wiki/livres" className={cls(location.pathname.startsWith('/wiki/livres'))}>
                    <Library size={15} />
                    <span>Liste des livres</span>
                  </Link>
                </li>
                <li>
                  <Link to="/wiki" className={cls(location.pathname === '/wiki')}>
                    <Upload size={15} />
                    <span>Publier</span>
                  </Link>
                </li>
                <li>
                  <a href={bookstackUrl} target="_blank" rel="noopener noreferrer"
                    title="Ouvrir BookStack dans un nouvel onglet"
                    className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors">
                    <ExternalLink size={15} />
                    <span className="flex-1">Ouvrir WIKI</span>
                  </a>
                </li>
              </ul>
            )}
          </li>
        )}

        <li>
          <Link to="/settings" className={cls(location.pathname === '/settings')}>
            <Settings size={15} />
            <span>Paramètres</span>
          </Link>
        </li>
      </ul>
      <div className="p-3 border-t border-gray-700 text-xs text-gray-500">
        Ollama · Tika · pgvector · n8n
      </div>
    </nav>
  )
}
