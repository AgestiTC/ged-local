/**
 * Sidebar — Navigation principale Matothèque
 */
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Copy, FileText, FolderOpen, FolderTree, Settings } from 'lucide-react'
import { systemApi } from '../../api'

const navItems = [
  { to: '/', label: 'Rapports', Icon: FileText },
  { to: '/ged', label: 'GED', Icon: FolderOpen },
  { to: '/doublons', label: 'Doublons', Icon: Copy },
  { to: '/reorganiser', label: 'Réorganiser', Icon: FolderTree },
  { to: '/settings', label: 'Paramètres', Icon: Settings },
]

export default function Sidebar() {
  const location = useLocation()
  // Version dynamique (source de vérité = fichier VERSION exposé par /api/version)
  const [version, setVersion] = useState<string | null>(null)
  useEffect(() => { systemApi.version().then(v => setVersion(v.version)).catch(() => {}) }, [])

  return (
    <nav className="w-52 bg-gray-900 text-white flex flex-col shrink-0">
      <div className="p-4 border-b border-gray-700">
        <h1 className="font-bold text-base tracking-tight">Matothèque</h1>
        <p className="text-xs text-gray-500 mt-0.5">{version ? `v${version} — ` : ''}100% local</p>
      </div>
      <ul className="flex-1 p-2 space-y-0.5">
        {navItems.map(({ to, label, Icon }) => {
          const active = location.pathname === to
          return (
            <li key={to}>
              <Link
                to={to}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
                  active ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                }`}
              >
                <Icon size={15} />
                <span>{label}</span>
              </Link>
            </li>
          )
        })}
      </ul>
      <div className="p-3 border-t border-gray-700 text-xs text-gray-500">
        Ollama · Tika · pgvector · n8n
      </div>
    </nav>
  )
}
