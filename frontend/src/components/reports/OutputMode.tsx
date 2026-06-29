/**
 * OutputMode — Sélecteur du mode de sortie du rapport
 * rapport_libre | remplir_template | classement
 */
import { FileText, Layout, ListOrdered, BarChart2, BookOpen, type LucideIcon } from 'lucide-react'
import { clsx } from 'clsx'
import { useReportStore } from '../../stores/reportStore'
import type { OutputMode as OutputModeType } from '../../types'

const MODES: { value: OutputModeType; label: string; description: string; Icon: LucideIcon }[] = [
  { value: 'rapport_libre', label: 'Rapport rédigé', description: 'Synthèse / analyse libre des documents', Icon: FileText },
  { value: 'remplir_template', label: 'Remplir un modèle', description: 'Compléter un fichier Word (.docx) à trous', Icon: Layout },
  { value: 'classement', label: 'Classement / tri', description: 'Classer, trier ou noter des éléments', Icon: ListOrdered },
  { value: 'comparatif', label: 'Tableau comparatif', description: 'Comparer des candidats / sociétés (Excel)', Icon: BarChart2 },
  { value: 'wiki', label: 'Tuto wiki', description: 'Rédiger un tuto et le publier sur le wiki', Icon: BookOpen },
]

export default function OutputMode() {
  const { outputMode, setOutputMode } = useReportStore()

  return (
    <div className="flex gap-2">
      {MODES.map(({ value, label, description, Icon }) => (
        <button
          key={value}
          onClick={() => setOutputMode(value)}
          className={clsx(
            'flex-1 flex flex-col items-center gap-1 p-2.5 rounded-lg border text-center transition-all text-xs',
            outputMode === value
              ? 'border-blue-400 bg-blue-50 text-blue-700'
              : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50',
          )}
        >
          <Icon size={15} />
          <span className="font-medium">{label}</span>
          <span className="text-gray-400 text-xs leading-tight">{description}</span>
        </button>
      ))}
    </div>
  )
}
