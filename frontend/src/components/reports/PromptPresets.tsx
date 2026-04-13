/**
 * PromptPresets — Sélecteur de prompts pré-enregistrés
 * Dropdown standalone (utilisable indépendamment de PromptEditor).
 */
import { useEffect, useState } from 'react'
import { BookOpen, ChevronDown } from 'lucide-react'
import { clsx } from 'clsx'
import { promptsApi } from '../../api'
import type { PromptPreset } from '../../types'

interface Props {
  onSelect: (preset: PromptPreset) => void
  className?: string
}

const CATEGORIE_LABELS: Record<string, string> = {
  rapport: 'Rapports',
  classement: 'Classements',
  extraction: 'Extraction',
  analyse: 'Analyse',
}

export default function PromptPresets({ onSelect, className }: Props) {
  const [presets, setPresets] = useState<PromptPreset[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    promptsApi.list()
      .then(d => setPresets(d.prompts))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  // Grouper par catégorie
  const grouped = presets.reduce<Record<string, PromptPreset[]>>((acc, p) => {
    const cat = p.categorie ?? 'autre'
    return { ...acc, [cat]: [...(acc[cat] ?? []), p] }
  }, {})

  const handleSelect = (preset: PromptPreset) => {
    onSelect(preset)
    setOpen(false)
  }

  return (
    <div className={clsx('relative', className)}>
      <button
        onClick={() => setOpen(o => !o)}
        disabled={loading || presets.length === 0}
        className={clsx(
          'flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors',
          open
            ? 'border-blue-300 bg-blue-50 text-blue-700'
            : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50',
          'disabled:opacity-40 disabled:cursor-not-allowed',
        )}
      >
        <BookOpen size={12} />
        <span>{loading ? 'Chargement…' : presets.length === 0 ? 'Aucun preset' : 'Presets'}</span>
        <ChevronDown size={11} className={clsx('transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <>
          {/* Overlay pour fermer au clic extérieur */}
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />

          <div className="absolute top-full left-0 mt-1 w-72 bg-white border border-gray-200 rounded-lg shadow-lg z-20 overflow-hidden max-h-80 overflow-y-auto">
            {Object.entries(grouped).map(([cat, items]) => (
              <div key={cat}>
                <div className="px-3 py-1.5 bg-gray-50 text-xs font-semibold text-gray-500 uppercase tracking-wide border-b border-gray-100">
                  {CATEGORIE_LABELS[cat] ?? cat}
                </div>
                {items.map(preset => (
                  <button
                    key={preset.id}
                    onClick={() => handleSelect(preset)}
                    className="w-full text-left px-3 py-2 hover:bg-blue-50 transition-colors"
                  >
                    <p className="text-xs font-medium text-gray-700">{preset.nom}</p>
                    {preset.description && (
                      <p className="text-xs text-gray-400 truncate mt-0.5">{preset.description}</p>
                    )}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
