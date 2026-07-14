/**
 * Header — Barre du haut avec indicateurs d'état des services
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { systemApi } from '../../api'
import JobsIndicator from './JobsIndicator'

interface ServiceStatus {
  tika: boolean | null
  ollama: string | null   // 3 états : 'ok' | 'busy' | 'down'
  n8n: string | null      // 3 états
  clamav: boolean | null
}

// Voyant 3 états : 🟢 ok · 🟠 occupé (joignable mais lent) · 🔴 injoignable (éteint).
function StatusDot({ ok, etat }: { ok?: boolean | null; etat?: string | null }) {
  const s: string | null = etat ?? (ok === null || ok === undefined ? null : ok ? 'ok' : 'down')
  const cls = s === 'ok' ? 'bg-green-400' : s === 'busy' ? 'bg-amber-400' : s === null ? 'bg-gray-300' : 'bg-red-400'
  const title = s === 'ok' ? 'Disponible' : s === 'busy' ? 'Occupé' : s === null ? '…' : 'Indisponible'
  return <span className={`w-2 h-2 rounded-full inline-block ${cls}`} title={title} />
}

export default function Header() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<ServiceStatus>({ tika: null, ollama: null, n8n: null, clamav: null })

  useEffect(() => {
    const check = async () => {
      try {
        const s = await systemApi.services()
        setStatus({
          tika: s.tika.ok,
          ollama: s.ollama.etat ?? (s.ollama.ok ? 'ok' : 'down'),
          n8n: s.n8n?.etat ?? (s.n8n?.ok ? 'ok' : 'down'),
          clamav: s.clamav?.ok ?? false,
        })
      } catch {
        setStatus({ tika: false, ollama: 'down', n8n: 'down', clamav: false })
      }
    }
    check()
    const interval = setInterval(check, 30_000)
    return () => clearInterval(interval)
  }, [])

  return (
    <header className="h-11 bg-white border-b border-gray-200 flex items-center justify-between px-4 shrink-0">
      {/* Navigation précédent / suivant */}
      <div className="flex items-center gap-1">
        <button type="button" onClick={() => navigate(-1)} title="Précédent"
          className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md">
          <ChevronLeft size={16} />
        </button>
        <button type="button" onClick={() => navigate(1)} title="Suivant"
          className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md">
          <ChevronRight size={16} />
        </button>
      </div>
      <div className="flex items-center gap-4 text-xs text-gray-500">
        <JobsIndicator />
        <span className="flex items-center gap-1.5">
          <StatusDot ok={status.tika} /> Tika
        </span>
        <span className="flex items-center gap-1.5">
          <StatusDot etat={status.ollama} /> Ollama
        </span>
        <span className="flex items-center gap-1.5">
          <StatusDot etat={status.n8n} /> n8n
        </span>
        <span className="flex items-center gap-1.5">
          <StatusDot ok={status.clamav} /> Antivirus
        </span>
      </div>
    </header>
  )
}
