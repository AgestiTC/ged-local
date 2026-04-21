/**
 * Spinner de chargement — utilisé dans toute l'application
 */
import { Loader2 } from 'lucide-react'
import { clsx } from 'clsx'

interface Props {
  size?: number
  className?: string
  label?: string
}

export default function LoadingSpinner({ size = 20, className, label }: Props) {
  return (
    <div className={clsx('flex items-center gap-2 text-gray-400', className)}>
      <Loader2 size={size} className="animate-spin" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  )
}
