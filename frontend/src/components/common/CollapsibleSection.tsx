/**
 * CollapsibleSection — section dépliable/repliable réutilisable
 * ============================================================
 * Titre + icône + chevron ; état ouvert/fermé mémorisé en localStorage si `id` fourni.
 * Utilisé sur la page Rapports (assistant + config) et, à terme, la page Paramètres.
 */
import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { clsx } from 'clsx'

interface Props {
  title: ReactNode
  icon?: ReactNode
  defaultOpen?: boolean
  id?: string                 // clé de persistance (localStorage)
  right?: ReactNode           // contenu aligné à droite de l'en-tête (badge, action…)
  children: ReactNode
  className?: string
}

export default function CollapsibleSection({ title, icon, defaultOpen = true, id, right, children, className }: Props) {
  const cle = id ? `collapse:${id}` : null
  const [open, setOpen] = useState(() => {
    if (cle) { const v = localStorage.getItem(cle); if (v !== null) return v === '1' }
    return defaultOpen
  })
  const toggle = () => {
    setOpen(o => { const n = !o; if (cle) localStorage.setItem(cle, n ? '1' : '0'); return n })
  }

  return (
    <section className={clsx('bg-white border border-gray-200 rounded-lg', className)}>
      <button type="button" onClick={toggle}
        className="w-full flex items-center gap-2 px-4 py-3 text-left">
        {open ? <ChevronDown size={16} className="text-gray-400 shrink-0" /> : <ChevronRight size={16} className="text-gray-400 shrink-0" />}
        {icon}
        <h2 className="text-sm font-semibold text-gray-800 flex-1">{title}</h2>
        {right}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </section>
  )
}
