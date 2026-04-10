import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import MainLayout from './components/layout/MainLayout'
import GEDPage from './pages/GEDPage'
import ReportsPage from './pages/ReportsPage'
import SettingsPage from './pages/SettingsPage'

/**
 * Application principale DocFlow AI.
 * Routes :
 *   /          → Rapports (page principale)
 *   /ged       → GED (recherche + navigation)
 *   /settings  → Paramètres
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<MainLayout />}>
          <Route index element={<ReportsPage />} />
          <Route path="ged" element={<GEDPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
