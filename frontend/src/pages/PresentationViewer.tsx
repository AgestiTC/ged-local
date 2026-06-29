/**
 * PresentationViewer — visionneuse de diaporama (reveal.js)
 * ========================================================
 * Page plein écran (hors layout). Navigation : flèches ← →, clic, molette ;
 * boutons Lecture/Pause (auto-slide), Plein écran, et téléchargement PPTX.
 * S'ouvre typiquement dans un nouvel onglet (`/presentation/:id`).
 */
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Play, Pause, Maximize, Download, Loader2 } from 'lucide-react'
// @ts-expect-error — reveal.js n'expose pas de types
import Reveal from 'reveal.js'
import 'reveal.js/dist/reveal.css'
import 'reveal.js/dist/theme/white.css'
import { presentationsApi, type Presentation } from '../api'

export default function PresentationViewer() {
  const { id } = useParams<{ id: string }>()
  const deckEl = useRef<HTMLDivElement>(null)
  const deck = useRef<any>(null)
  const [pres, setPres] = useState<Presentation | null>(null)
  const [erreur, setErreur] = useState(false)
  const [auto, setAuto] = useState(false)

  useEffect(() => {
    if (!id) return
    presentationsApi.get(id).then(setPres).catch(() => setErreur(true))
  }, [id])

  useEffect(() => {
    if (!pres || !deckEl.current) return
    const r = new Reveal(deckEl.current, {
      embedded: true, hash: false, controls: true, progress: true,
      slideNumber: 'c/t', transition: 'slide', keyboard: true,
    })
    r.initialize()
    deck.current = r
    return () => { try { r.destroy() } catch { /* ignore */ } }
  }, [pres])

  const toggleAuto = () => {
    if (!deck.current) return
    deck.current.configure({ autoSlide: auto ? 0 : 5000 })
    setAuto(a => !a)
  }
  const plein = () => { deckEl.current?.requestFullscreen?.() }

  if (erreur) return <Centre>Présentation introuvable.</Centre>
  if (!pres) return <Centre><Loader2 className="animate-spin" /> Chargement de la présentation…</Centre>

  return (
    <div className="fixed inset-0 bg-neutral-900">
      {/* Barre de contrôles */}
      <div className="absolute top-3 right-3 z-20 flex items-center gap-2">
        <button onClick={toggleAuto} title={auto ? 'Pause' : 'Lecture automatique'}
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-white/90 hover:bg-white text-gray-800 shadow">
          {auto ? <Pause size={15} /> : <Play size={15} />}{auto ? 'Pause' : 'Lecture'}
        </button>
        <button onClick={plein} title="Plein écran"
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-white/90 hover:bg-white text-gray-800 shadow">
          <Maximize size={15} /> Plein écran
        </button>
        <a href={presentationsApi.pptxUrl(pres.id)} title="Télécharger le PPTX"
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white shadow">
          <Download size={15} /> PPTX
        </a>
      </div>

      <div className="reveal h-full" ref={deckEl}>
        <div className="slides">
          {/* Diapo de titre */}
          <section>
            <h1>{pres.titre}</h1>
            {pres.theme && <p style={{ color: '#666' }}>{pres.theme}</p>}
            <p style={{ fontSize: '0.5em', color: '#999' }}>Généré par Matothèque — IA locale</p>
          </section>
          {/* Diapos contenu */}
          {pres.slides.map((s, i) => (
            <section key={i}>
              <h2>{s.titre}</h2>
              <ul>{s.points.map((p, j) => <li key={j}>{p}</li>)}</ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}

function Centre({ children }: { children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 bg-neutral-900 text-white flex items-center justify-center gap-2 text-sm">
      {children}
    </div>
  )
}
