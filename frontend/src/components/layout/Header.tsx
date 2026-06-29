/**
 * Header — Barre du haut avec indicateurs d'état des services
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { systemApi } from '../../api'

interface ServiceStatus {
  tika: boolean | null
  ollama: boolean | null
  n8n: boolean | null
  clamav: boolean | null
}

function StatusDot({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="w-2 h-2 rounded-full bg-gray-300 inline-block" />
  return (
    <span
      className={`w-2 h-2 rounded-full inline-block ${ok ? 'bg-green-400' : 'bg-red-400'}`}
      title={ok ? 'Disponible' : 'Indisponible'}
    />
  )
}

export default function Header() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<ServiceStatus>({ tika: null, ollama: null, n8n: null, clamav: null })

  useEffect(() => {
    const check = async () => {
      try {
        const s = await systemApi.services()
        setStatus({ tika: s.tika.ok, ollama: s.ollama.ok, n8n: s.n8n?.ok ?? false, clamav: s.clamav?.ok ?? false })
      } catch {
        setStatus({ tika: false, ollama: false, n8n: false, clamav: false })
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
        <span className="flex items-center gap-1.5">
          <StatusDot ok={status.tika} /> Tika
        </span>
        <span className="flex items-center gap-1.5">
          <StatusDot ok={status.ollama} /> Ollama
        </span>
        <span className="flex items-center gap-1.5">
          <StatusDot ok={status.n8n} /> n8n
        </span>
        <span className="flex items-center gap-1.5">
          <StatusDot ok={status.clamav} /> Antivirus
        </span>
      </div>
    </header>
  )
}
