/**
 * DocumentsMarche — « Documents du marché » du Tableau comparatif (CCTP, règlement de consultation…).
 * ==================================================================================================
 * Ce que le marché EXIGE, distinct de ce que chaque candidat OFFRE. Pour chaque critère, Matothèque
 * en retrouve les passages pertinents et demande à l'IA si l'offre y répond, en partie, ou pas du
 * tout (demande du 11/10/2026). Facultatif : sans eux, l'analyse se fait comme avant.
 */
import { useEffect, useState } from 'react'
import { FileText, PenLine, Plus, Sparkles, X } from 'lucide-react'
import { documentsApi } from '../../api'
import PromptEditor from './PromptEditor'
import ConsigneBaseModal from './ConsigneBaseModal'

interface Props {
  ids: string[]
  onChange: (ids: string[]) => void
  /** Documents cochés dans l'arborescence « Quels documents ? ». */
  selectionIds: string[]
  /** Prépare un rapport sur ces documents : « analyse » (fond, forme, manques, points forts)
   *  ou « corrigee » (passages réécrits et clauses à ajouter). */
  onAnalyser?: (type: 'analyse' | 'corrigee') => void
  /** Instructions complémentaires de l'acheteur, ajoutées aux consignes d'analyse / de correction. */
  consignes: string
  onConsignesChange: (texte: string) => void
}

const PLACEHOLDER_CONSIGNES = `Ce que l'IA doit regarder en plus, par exemple :
• Vérifie la cohérence des délais entre le CCTP et le règlement
• Insiste sur la clarté des pénalités et des niveaux de service
• Propose des exigences mesurables pour chaque critère de notation`

export default function DocumentsMarche({ ids, onChange, selectionIds, onAnalyser, consignes, onConsignesChange }: Props) {
  const [noms, setNoms] = useState<Record<string, string>>({})
  // Case cochée d'office quand des consignes existent déjà (projet rouvert).
  const [avecConsignes, setAvecConsignes] = useState(consignes.trim().length > 0)
  const [voirBase, setVoirBase] = useState(false)

  useEffect(() => {
    ids.filter(id => !(id in noms)).forEach(id => {
      documentsApi.get(id)
        .then(d => setNoms(prev => ({ ...prev, [id]: d.nom })))
        .catch(() => setNoms(prev => ({ ...prev, [id]: 'Document introuvable' })))
    })
  }, [ids, noms])

  const nouveaux = selectionIds.filter(id => !ids.includes(id))

  return (
    <div className="space-y-2 text-xs">
      {ids.length > 0 && (
        <ul className="space-y-1">
          {ids.map(id => (
            <li key={id} className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-amber-50 border border-amber-100">
              <FileText size={12} className="text-amber-600 shrink-0" />
              <span className="flex-1 min-w-0 truncate text-gray-700">{noms[id] ?? '…'}</span>
              <button
                type="button"
                onClick={() => onChange(ids.filter(x => x !== id))}
                title="Retirer des documents du marché"
                className="text-gray-400 hover:text-red-500"
              >
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        disabled={nouveaux.length === 0}
        onClick={() => onChange([...ids, ...nouveaux])}
        className="flex items-center justify-center gap-1.5 w-full py-2 rounded-lg border border-amber-200 bg-amber-50 text-amber-800 font-medium hover:bg-amber-100 disabled:opacity-50 transition-colors"
      >
        <Plus size={12} />
        {nouveaux.length > 0
          ? `Utiliser les ${nouveaux.length} document(s) coché(s) comme documents du marché`
          : 'Cochez le CCTP / règlement dans « Quels documents ? »'}
      </button>
      {onAnalyser && ids.length > 0 && (
        <label className="flex items-center gap-2 text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={avecConsignes}
            onChange={e => setAvecConsignes(e.target.checked)}
            className="rounded border-gray-300 text-violet-600 focus:ring-violet-400"
          />
          Je souhaite donner des instructions complémentaires
        </label>
      )}
      {onAnalyser && ids.length > 0 && avecConsignes && (
        // Même éditeur que les Instructions (prompts enregistrés, 💾, ⚙, relecture par l'IA), avec
        // ses propres prompts : catégorie « reference ».
        <PromptEditor
          value={consignes}
          onChange={onConsignesChange}
          categorie="reference"
          mode="reference"
          placeholder={PLACEHOLDER_CONSIGNES}
        />
      )}
      {onAnalyser && ids.length > 0 && (
        <div className="grid grid-cols-2 gap-1.5">
          <button
            type="button"
            onClick={() => onAnalyser('analyse')}
            title="Un rapport constructif : fond, forme, pertinence, manques et points forts"
            className="flex items-center justify-center gap-1 py-2 px-1.5 rounded-lg border border-violet-200 bg-violet-50 text-violet-700 font-medium hover:bg-violet-100 transition-colors"
          >
            <Sparkles size={12} className="shrink-0" /> Analyser
          </button>
          <button
            type="button"
            onClick={() => onAnalyser('corrigee')}
            title="Passages réécrits (avant → après) et clauses à ajouter, prêts à copier — exportables en PDF / Word"
            className="flex items-center justify-center gap-1 py-2 px-1.5 rounded-lg border border-violet-200 bg-white text-violet-700 font-medium hover:bg-violet-50 transition-colors"
          >
            <PenLine size={12} className="shrink-0" /> Version corrigée
          </button>
        </div>
      )}
      {onAnalyser && ids.length > 0 && (
        <button type="button" onClick={() => setVoirBase(true)}
          className="flex items-center gap-1 text-violet-700 hover:underline">
          <FileText size={12} /> Voir / modifier la consigne de base
        </button>
      )}
      {voirBase && <ConsigneBaseModal onClose={() => setVoirBase(false)} />}
      <p className="text-gray-400 leading-relaxed">
        Ne les mettez pas dans un candidat : ce sont les exigences auxquelles chaque offre est confrontée.
      </p>
    </div>
  )
}
