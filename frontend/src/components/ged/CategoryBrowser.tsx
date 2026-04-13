/**
 * CategoryBrowser — Navigation par catégories dans la GED
 * Affiche les catégories avec compteurs, filtre actif en surbrillance.
 */
import { FolderOpen, X } from 'lucide-react'
import { clsx } from 'clsx'
import { useGEDStore } from '../../stores/gedStore'

interface Props {
  className?: string
}

export default function CategoryBrowser({ className }: Props) {
  const { categories, filters, setFilters, search } = useGEDStore()

  if (categories.length === 0) return null

  const activeCategory = filters.categorie

  const selectCategory = (categorie: string) => {
    const next = categorie === activeCategory ? undefined : categorie
    setFilters({ ...filters, categorie: next })
    search()
  }

  return (
    <div className={clsx('space-y-1', className)}>
      {/* Catégorie active */}
      {activeCategory && (
        <button
          onClick={() => selectCategory(activeCategory)}
          className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs bg-blue-50 text-blue-700 border border-blue-200"
        >
          <FolderOpen size={11} />
          <span className="flex-1 text-left truncate">{activeCategory}</span>
          <X size={10} />
        </button>
      )}

      {/* Liste */}
      {categories
        .filter(c => c.categorie !== activeCategory)
        .slice(0, 15)
        .map(c => (
          <button
            key={c.categorie}
            onClick={() => selectCategory(c.categorie)}
            className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs text-gray-600 hover:bg-gray-50 transition-colors"
          >
            <FolderOpen size={11} className="text-gray-400 shrink-0" />
            <span className="flex-1 text-left truncate">{c.categorie}</span>
            <span className="text-gray-400 shrink-0 tabular-nums">{c.nb_documents}</span>
          </button>
        ))}
    </div>
  )
}
