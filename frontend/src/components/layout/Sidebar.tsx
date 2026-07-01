/**
 * Sidebar — Navigation principale Matothèque
 * Menus DYNAMIQUES : un item n'apparaît que si le service correspondant est configuré
 * (BookStack → Publier + WIKI ; token HuggingFace → HuggingFace ; liens → Administration).
 * Pas de menu parasite.
 */
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { BookOpen, Boxes, Copy, ExternalLink, LayoutGrid, PenSquare, FolderOpen, FolderTree, Settings, Upload } from 'lucide-react'
import { systemApi } from '../../api'

export default function Sidebar() {
  const location = useLocation()
  const [version, setVersion] = useState<string | null>(null)
  const [bookstackUrl, setBookstackUrl] = useState('')
  const [hfConfig, setHfConfig] = useState(false)
  const [adminCount, setAdminCount] = useState(0)

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
    { to: '/wiki', label: 'Publier', Icon: Upload, show: !!bookstackUrl },
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

        {/* Ouvrir WIKI (BookStack externe) — seulement si l'URL est configurée. */}
        {bookstackUrl && (
          <li>
            <a href={bookstackUrl} target="_blank" rel="noopener noreferrer"
              title="Ouvrir BookStack dans un nouvel onglet"
              className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors">
              <BookOpen size={15} />
              <span className="flex-1">Ouvrir WIKI</span>
              <ExternalLink size={12} className="text-gray-500" />
            </a>
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
