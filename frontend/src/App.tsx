import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import MainLayout from './components/layout/MainLayout'
import ReportsPage from './pages/ReportsPage'
import ErrorBoundary from './components/common/ErrorBoundary'
import LoadingSpinner from './components/common/LoadingSpinner'

const GEDPage = lazy(() => import('./pages/GEDPage'))
const DuplicatesPage = lazy(() => import('./pages/DuplicatesPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-full py-20">
      <LoadingSpinner label="Chargement…" />
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<MainLayout />}>
          <Route index element={<ErrorBoundary><ReportsPage /></ErrorBoundary>} />
          <Route path="ged" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <GEDPage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="doublons" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <DuplicatesPage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="settings" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <SettingsPage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
