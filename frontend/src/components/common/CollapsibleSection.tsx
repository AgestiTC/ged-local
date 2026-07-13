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
  id?: string                 // clé de persistance (localStorage) + ancre DOM (#section-<id>)
  right?: ReactNode           // contenu aligné à droite de l'en-tête (badge, action…)
  children: ReactNode
  className?: string
  open?: boolean              // mode contrôlé : si fourni, le parent pilote l'ouverture
  onToggle?: (next: boolean) => void
  hidden?: boolean            // masque totalement la section (ex. filtre de recherche)
}

export default function CollapsibleSection({ title, icon, defaultOpen = true, id, right, children, className, open, onToggle, hidden }: Props) {
  const cle = id ? `collapse:${id}` : null
  const controlled = open !== undefined
  const [internal, setInternal] = useState(() => {
    if (cle) { const v = localStorage.getItem(cle); if (v !== null) return v === '1' }
    return defaultOpen
  })
  const isOpen = controlled ? open : internal
  const toggle = () => {
    const n = !isOpen
    if (cle) localStorage.setItem(cle, n ? '1' : '0')   // persiste dans les deux modes
    if (controlled) onToggle?.(n); else setInternal(n)
  }

  if (hidden) return null

  return (
    <section id={id ? `section-${id}` : undefined}
      className={clsx('bg-white border border-gray-200 rounded-lg scroll-mt-4', className)}>
      <button type="button" onClick={toggle}
        className="w-full flex items-center gap-2 px-4 py-3 text-left">
        {isOpen ? <ChevronDown size={16} className="text-gray-400 shrink-0" /> : <ChevronRight size={16} className="text-gray-400 shrink-0" />}
        {icon}
        <h2 className="text-sm font-semibold text-gray-800 flex-1">{title}</h2>
        {right}
      </button>
      {isOpen && <div className="px-4 pb-4">{children}</div>}
    </section>
  )
}
