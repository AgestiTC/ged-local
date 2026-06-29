/**
 * Step — Étape numérotée du parcours guidé de génération de rapport.
 * Affiche une pastille numérotée + une carte de contenu, reliée par un trait
 * vertical (sauf la dernière). Utilisé par ReportsPage.
 */
import type { ReactNode } from 'react'
import { clsx } from 'clsx'

interface Props {
  n: number
  title: string
  hint?: string
  /** Masque le trait vertical de liaison (dernière étape). */
  last?: boolean
  /** Étape mise en avant (ex : action finale « Générer »). */
  accent?: boolean
  children: ReactNode
}

export default function Step({ n, title, hint, last, accent, children }: Props) {
  return (
    <div className="relative pl-10">
      {/* Trait de liaison vers l'étape suivante */}
      {!last && <span className="absolute left-[15px] top-8 -bottom-3 w-px bg-gray-200" aria-hidden />}

      {/* Pastille numérotée */}
      <span
        className={clsx(
          'absolute left-0 top-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold shrink-0',
          accent ? 'bg-blue-600 text-white' : 'bg-blue-100 text-blue-700',
        )}
      >
        {n}
      </span>

      <div className={clsx('rounded-xl border p-3.5', accent ? 'border-blue-200 bg-blue-50/40' : 'border-gray-200 bg-white')}>
        <div className="mb-2.5">
          <h3 className="text-sm font-semibold text-gray-800 leading-none">{title}</h3>
          {hint && <p className="text-[11px] text-gray-400 mt-1">{hint}</p>}
        </div>
        {children}
      </div>
    </div>
  )
}
