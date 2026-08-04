/**
 * Header — Barre du haut avec indicateurs d'état des services
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Menu } from 'lucide-react'
import { systemApi } from '../../api'
import JobsIndicator from './JobsIndicator'

interface ServiceStatus {
  tika: boolean | null
  ollama: string | null   // 3 états : 'ok' | 'busy' | 'down'
  n8n: string | null      // 3 états
  clamav: boolean | null
  // Transcription audio : optionnelle → `null` tant que non configurée (badge masqué).
  transcription: boolean | null
}

// Voyant 3 états : 🟢 ok · 🟠 occupé (joignable mais lent) · 🔴 injoignable (éteint).
function StatusDot({ ok, etat }: { ok?: boolean | null; etat?: string | null }) {
  const s: string | null = etat ?? (ok === null || ok === undefined ? null : ok ? 'ok' : 'down')
  const cls = s === 'ok' ? 'bg-green-400' : s === 'busy' ? 'bg-amber-400' : s === null ? 'bg-gray-300' : 'bg-red-400'
  const title = s === 'ok' ? 'Disponible' : s === 'busy' ? 'Occupé' : s === null ? '…' : 'Indisponible'
  return <span className={`w-2 h-2 rounded-full inline-block ${cls}`} title={title} />
}

export default function Header({ onBurger }: { onBurger?: () => void }) {
  const navigate = useNavigate()
  const [status, setStatus] = useState<ServiceStatus>({ tika: null, ollama: null, n8n: null, clamav: null, transcription: null })

  useEffect(() => {
    const check = async () => {
      try {
        const s = await systemApi.services()
        setStatus({
          tika: s.tika.ok,
          ollama: s.ollama.etat ?? (s.ollama.ok ? 'ok' : 'down'),
          n8n: s.n8n?.etat ?? (s.n8n?.ok ? 'ok' : 'down'),
          clamav: s.clamav?.ok ?? false,
          // Non configurée → `null` : le badge ne s'affiche pas (feature optionnelle).
          transcription: s.transcription?.configure ? !!s.transcription.ok : null,
        })
      } catch {
        setStatus({ tika: false, ollama: 'down', n8n: 'down', clamav: false, transcription: null })
      }
    }
    check()
    const interval = setInterval(check, 30_000)
    return () => clearInterval(interval)
  }, [])

  return (
    <header className="h-11 bg-white border-b border-gray-200 flex items-center justify-between px-2 sm:px-4 shrink-0">
      {/* Navigation : burger (mobile) + précédent / suivant */}
      <div className="flex items-center gap-1">
        <button type="button" onClick={onBurger} title="Menu"
          className="md:hidden p-1.5 text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded-md">
          <Menu size={18} />
        </button>
        <button type="button" onClick={() => navigate(-1)} title="Précédent"
          className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md">
          <ChevronLeft size={16} />
        </button>
        <button type="button" onClick={() => navigate(1)} title="Suivant"
          className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md">
          <ChevronRight size={16} />
        </button>
      </div>
      {/* Statuts : libellés masqués sous `sm` (juste les pastilles) pour tenir sur smartphone. */}
      <div className="flex items-center gap-2.5 sm:gap-4 text-xs text-gray-500">
        <JobsIndicator />
        <span className="flex items-center gap-1.5" title="Tika">
          <StatusDot ok={status.tika} /> <span className="hidden sm:inline">Tika</span>
        </span>
        <span className="flex items-center gap-1.5" title="Ollama">
          <StatusDot etat={status.ollama} /> <span className="hidden sm:inline">Ollama</span>
        </span>
        <span className="flex items-center gap-1.5" title="n8n">
          <StatusDot etat={status.n8n} /> <span className="hidden sm:inline">n8n</span>
        </span>
        <span className="flex items-center gap-1.5" title="Antivirus">
          <StatusDot ok={status.clamav} /> <span className="hidden sm:inline">Antivirus</span>
        </span>
        {/* Transcription : badge affiché uniquement si un serveur est configuré. */}
        {status.transcription !== null && (
          <span className="flex items-center gap-1.5" title="Transcription audio (parole → texte)">
            <StatusDot ok={status.transcription} /> <span className="hidden sm:inline">Transcription</span>
          </span>
        )}
      </div>
    </header>
  )
}
