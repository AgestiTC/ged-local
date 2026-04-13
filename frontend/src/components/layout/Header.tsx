/**
 * Header — Barre du haut avec indicateurs d'état des services
 */
import { useEffect, useState } from 'react'
import { systemApi } from '../../api'

interface ServiceStatus {
  tika: boolean | null
  ollama: boolean | null
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
  const [status, setStatus] = useState<ServiceStatus>({ tika: null, ollama: null })

  useEffect(() => {
    const check = async () => {
      try {
        const health = await systemApi.health()
        setStatus({
          tika: health.services.tika.disponible,
          ollama: health.services.ollama.disponible,
        })
      } catch {
        setStatus({ tika: false, ollama: false })
      }
    }
    check()
    const interval = setInterval(check, 30_000)
    return () => clearInterval(interval)
  }, [])

  return (
    <header className="h-11 bg-white border-b border-gray-200 flex items-center justify-between px-4 shrink-0">
      <span className="text-sm font-medium text-gray-600">DocFlow AI</span>
      <div className="flex items-center gap-4 text-xs text-gray-500">
        <span className="flex items-center gap-1.5">
          <StatusDot ok={status.tika} /> Tika
        </span>
        <span className="flex items-center gap-1.5">
          <StatusDot ok={status.ollama} /> Ollama
        </span>
      </div>
    </header>
  )
}
