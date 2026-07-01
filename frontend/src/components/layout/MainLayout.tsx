/**
 * Layout principal — Sidebar + Header + contenu
 * TODO Phase 2 : styling complet
 */
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'
import GenerationGuard from '../reports/GenerationGuard'

export default function MainLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-auto bg-gray-50">
          <Outlet />
        </main>
      </div>
      {/* Avertit tant qu'un rapport se génère (SSE lié à l'onglet) */}
      <GenerationGuard />
    </div>
  )
}
