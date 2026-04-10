/**
 * Sidebar — Navigation principale
 * TODO Phase 2
 */
import { Link, useLocation } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'Rapports', icon: '📄' },
  { to: '/ged', label: 'GED', icon: '🗂️' },
  { to: '/settings', label: 'Paramètres', icon: '⚙️' },
]

export default function Sidebar() {
  const location = useLocation()
  return (
    <nav className="w-56 bg-gray-900 text-white flex flex-col">
      <div className="p-4 border-b border-gray-700">
        <h1 className="font-bold text-lg">DocFlow AI</h1>
        <p className="text-xs text-gray-400">v0.1.0</p>
      </div>
      <ul className="flex-1 p-2 space-y-1">
        {navItems.map(({ to, label, icon }) => (
          <li key={to}>
            <Link
              to={to}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors
                ${location.pathname === to
                  ? 'bg-primary-600 text-white'
                  : 'text-gray-300 hover:bg-gray-800'
                }`}
            >
              <span>{icon}</span>
              <span>{label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}
