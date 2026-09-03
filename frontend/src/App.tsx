import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import MainLayout from './components/layout/MainLayout'
import ReportsPage from './pages/ReportsPage'
import ErrorBoundary from './components/common/ErrorBoundary'
import LoadingSpinner from './components/common/LoadingSpinner'

const GEDPage = lazy(() => import('./pages/GEDPage'))
const DuplicatesPage = lazy(() => import('./pages/DuplicatesPage'))
const LinksPage = lazy(() => import('./pages/LinksPage'))
const ReorganizePage = lazy(() => import('./pages/ReorganizePage'))
const RegroupementsPage = lazy(() => import('./pages/RegroupementsPage'))
const DossiersPage = lazy(() => import('./pages/DossiersPage'))
const DossierDetailPage = lazy(() => import('./pages/DossierDetailPage'))
const WikiPage = lazy(() => import('./pages/WikiPage'))
const WikiBooksPage = lazy(() => import('./pages/WikiBooksPage'))
const WikiBookReader = lazy(() => import('./pages/WikiBookReader'))
const HuggingFacePage = lazy(() => import('./pages/HuggingFacePage'))
const AdminPage = lazy(() => import('./pages/AdminPage'))
const LogsPage = lazy(() => import('./pages/LogsPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const PresentationViewer = lazy(() => import('./pages/PresentationViewer'))

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
        {/* Visionneuse plein écran — hors layout (nouvel onglet) */}
        <Route path="presentation/:id" element={
          <Suspense fallback={<PageLoader />}>
            <PresentationViewer />
          </Suspense>
        } />
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
          <Route path="liens" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <LinksPage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="reorganiser" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <ReorganizePage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="regroupements" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <RegroupementsPage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="dossiers" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <DossiersPage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="dossiers/:slug" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <DossierDetailPage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="wiki" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <WikiPage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="wiki/livres" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <WikiBooksPage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="wiki/livres/:id" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <WikiBookReader />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="huggingface" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <HuggingFacePage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="admin" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <AdminPage />
              </Suspense>
            </ErrorBoundary>
          } />
          <Route path="logs" element={
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <LogsPage />
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
