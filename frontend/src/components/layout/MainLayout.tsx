/**
 * Layout principal — Sidebar + Header + contenu.
 * Responsive : au-delà de `md` la sidebar est fixe ; en dessous (tablette/smartphone) elle
 * devient un tiroir off-canvas ouvert par le bouton burger du Header (avec fond assombri).
 */
import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'
import GenerationGuard from '../reports/GenerationGuard'

export default function MainLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const location = useLocation()

  // Referme le tiroir à chaque navigation (sur mobile, on clique un lien → on veut voir la page).
  useEffect(() => { setDrawerOpen(false) }, [location.pathname])

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Fond assombri (mobile uniquement, quand le tiroir est ouvert) */}
      {drawerOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setDrawerOpen(false)} aria-hidden />
      )}
      <Sidebar drawerOpen={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        <Header onBurger={() => setDrawerOpen(o => !o)} />
        <main className="flex-1 overflow-auto bg-gray-50">
          <Outlet />
        </main>
      </div>
      {/* Avertit tant qu'un rapport se génère (SSE lié à l'onglet) */}
      <GenerationGuard />
    </div>
  )
}
