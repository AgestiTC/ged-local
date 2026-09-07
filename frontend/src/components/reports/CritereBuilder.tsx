/**
 * CritereBuilder — Étape « Critères de comparaison » du mode Tableau comparatif.
 * =============================================================================
 * Les critères = les colonnes du tableau. Trois façons de les obtenir, et **aucune
 * n'est obligatoire** : sans rien fournir, l'IA les déduit des documents au lancement.
 *
 *   • IA        → l'IA propose une liste, ÉDITABLE avant de générer (ou rien du tout).
 *   • Manuel    → un critère par ligne, saisi à la main.
 *   • Template  → un .xlsx dont la ligne 1 porte les colonnes (mise en forme conservée).
 */
import { useState } from 'react'
import { Sparkles, PencilLine, Table2, Plus, X, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { compareApi } from '../../api'
import type { CritereSource } from '../../types'
import { useToast } from '../common/Toast'
import TemplateUpload from './TemplateUpload'

interface Props {
  source: CritereSource
  onSourceChange: (source: CritereSource) => void
  colonnes: string[]
  onColonnesChange: (colonnes: string[]) => void
  templateId?: string
  onTemplateChange: (templateId: string | undefined) => void
  /** Documents (tous groupes confondus) servant d'échantillon à la proposition IA. */
  documentIds: string[]
  instructions?: string
  model?: string
}

const SOURCES: { value: CritereSource; label: string; Icon: typeof Sparkles }[] = [
  { value: 'ia', label: 'L\'IA propose', Icon: Sparkles },
  { value: 'manuel', label: 'Je les saisis', Icon: PencilLine },
  { value: 'template', label: 'Template Excel', Icon: Table2 },
]

export default function CritereBuilder({
  source, onSourceChange, colonnes, onColonnesChange,
  templateId, onTemplateChange, documentIds, instructions, model,
}: Props) {
  const [chargement, setChargement] = useState(false)
  const toast = useToast()

  const proposer = async () => {
    if (documentIds.length === 0) {
      toast.error('Ajoutez d\'abord des documents dans vos groupes')
      return
    }
    setChargement(true)
    try {
      const { colonnes: proposees } = await compareApi.proposerCriteres({
        document_ids: documentIds.slice(0, 6),
        instructions: instructions?.trim() || undefined,
        model,
      })
      onColonnesChange(proposees)
      toast.success(`${proposees.length} critère(s) proposé(s) — modifiables avant génération`)
    } catch {
      toast.error('L\'IA n\'a pas pu proposer de critères (Ollama ?)')
    } finally {
      setChargement(false)
    }
  }

  const modifier = (index: number, valeur: string) =>
    onColonnesChange(colonnes.map((c, i) => (i === index ? valeur : c)))

  const retirer = (index: number) =>
    onColonnesChange(colonnes.filter((_, i) => i !== index))

  const ajouter = () => onColonnesChange([...colonnes, ''])

  return (
    <div className="space-y-3">
      {/* Choix de la provenance des critères */}
      <div className="flex rounded-lg border border-gray-200 p-0.5 bg-gray-50 text-xs">
        {SOURCES.map(({ value, label, Icon }) => (
          <button
            key={value}
            type="button"
            onClick={() => onSourceChange(value)}
            className={clsx(
              'flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md font-medium transition-colors',
              source === value ? 'bg-white text-blue-700 shadow-sm' : 'text-gray-500 hover:text-gray-700',
            )}
          >
            <Icon size={13} /> {label}
          </button>
        ))}
      </div>

      {source === 'template' ? (
        <>
          <p className="text-xs text-gray-500 leading-relaxed">
            Le tableau reprendra <strong>les colonnes de la ligne 1</strong> du fichier, et sa mise en forme.
          </p>
          <TemplateUpload selectedTemplateId={templateId} onSelect={onTemplateChange} />
        </>
      ) : (
        <>
          {source === 'ia' && (
            <div className="space-y-2">
              <p className="text-xs text-gray-500 leading-relaxed">
                Laissez vide pour que l'IA détermine les critères pendant la génération, ou faites-les
                proposer maintenant pour les relire et les corriger.
              </p>
              <button
                type="button"
                onClick={proposer}
                disabled={chargement}
                className="flex items-center justify-center gap-1.5 w-full py-2 rounded-lg border border-violet-200 bg-violet-50 text-violet-700 text-xs font-medium hover:bg-violet-100 disabled:opacity-60 transition-colors"
              >
                {chargement ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                {chargement ? 'Lecture des documents…' : 'Proposer des critères'}
              </button>
            </div>
          )}

          {colonnes.length > 0 && (
            <div className="space-y-1.5">
              {colonnes.map((colonne, index) => (
                <div key={index} className="flex items-center gap-1.5">
                  <span className="text-xs text-gray-300 w-4 text-right shrink-0">{index + 1}</span>
                  <input
                    value={colonne}
                    onChange={e => modifier(index, e.target.value)}
                    placeholder="Ex : Franchise, Plafond d'indemnisation…"
                    className="flex-1 min-w-0 text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 outline-none focus:border-blue-300 text-gray-700 placeholder-gray-400"
                  />
                  <button
                    type="button"
                    onClick={() => retirer(index)}
                    title="Retirer ce critère"
                    className="p-1 text-gray-300 hover:text-red-500 transition-colors shrink-0"
                  >
                    <X size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            type="button"
            onClick={ajouter}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700"
          >
            <Plus size={13} /> Ajouter un critère
          </button>
        </>
      )}
    </div>
  )
}
