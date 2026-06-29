/**
 * ResultPanel — panneau « Résultat » dynamique unifié (colonne droite Rapports)
 * =============================================================================
 * Un SEUL panneau dont le titre et le contenu s'adaptent à l'action en cours :
 *   • comparatif   → progression du rapport comparatif
 *   • propositions → documents proposés par l'Assistant IA (cochables)
 *   • génération   → stream du rapport en cours
 *   • résultat     → rapport terminé + actions
 *   • aperçu       → récap « Votre rapport » avant génération
 */
import { useEffect, useState } from 'react'
import { clsx } from 'clsx'
import { FileText, Sparkles } from 'lucide-react'
import { useReportStore } from '../../stores/reportStore'
import { useReportAssistantStore } from '../../stores/reportAssistantStore'
import ReportPreview from './ReportPreview'
import AssistantProposals from './AssistantProposals'
import CompareProgress from './CompareProgress'

interface Props {
  isComparatif: boolean
  compareJobId: string | null
  groupeNoms: string[]
  onComparatifComplete: () => void
  onComparatifError: (msg: string) => void
}

export default function ResultPanel({
  isComparatif, compareJobId, groupeNoms, onComparatifComplete, onComparatifError,
}: Props) {
  const { isGenerating, rapportEnCours, rapportFinal } = useReportStore()
  const { pieces, loading: assistantLoading } = useReportAssistantStore()

  const contenu = rapportEnCours || rapportFinal
  const hasPropositions = !!pieces || assistantLoading
  // Onglet visible uniquement quand on a des propositions ET pas (encore) de rapport
  const choix = !isComparatif && hasPropositions && !contenu && !isGenerating
  const [tab, setTab] = useState<'propositions' | 'apercu'>('propositions')

  // À l'arrivée de nouvelles propositions, basculer dessus
  useEffect(() => { if (hasPropositions) setTab('propositions') }, [pieces, assistantLoading])

  // ── Titre adaptatif ──
  const titre = isComparatif
    ? 'Comparatif — progression'
    : isGenerating && !contenu
    ? 'Génération en cours…'
    : contenu
    ? 'Résultat'
    : choix && tab === 'propositions'
    ? 'Documents proposés'
    : 'Aperçu'

  // ── Contenu ──
  const corps = () => {
    if (isComparatif) {
      return compareJobId ? (
        <CompareProgress
          jobId={compareJobId}
          groupeNoms={groupeNoms}
          onComplete={onComparatifComplete}
          onError={onComparatifError}
        />
      ) : (
        <div className="h-full flex flex-col items-center justify-center text-center text-gray-400 gap-2">
          <p className="text-xs">Configurez vos groupes et cliquez sur</p>
          <p className="text-xs font-medium text-gray-500">"Générer le rapport comparatif"</p>
        </div>
      )
    }
    // Propositions de l'Assistant (tant qu'aucun rapport n'est lancé)
    if (choix && tab === 'propositions') return <AssistantProposals />
    // Sinon : récap (vide) ou rapport (en cours / terminé)
    return <ReportPreview />
  }

  return (
    <aside className="flex-1 min-w-0 bg-white rounded-lg border border-gray-200 p-4 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between mb-3 shrink-0">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{titre}</h2>

        {/* Bascule Propositions ⇄ Aperçu (seulement quand pertinent) */}
        {choix && (
          <div className="flex rounded-md border border-gray-200 overflow-hidden text-xs">
            {([
              { key: 'propositions', label: 'Proposés', Icon: Sparkles },
              { key: 'apercu', label: 'Aperçu', Icon: FileText },
            ] as const).map(({ key, label, Icon }) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className={clsx('flex items-center gap-1 px-2 py-1',
                  tab === key ? 'bg-gray-100 font-medium text-gray-800' : 'text-gray-500 hover:text-gray-700')}
              >
                <Icon size={11} /> {label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        {corps()}
      </div>
    </aside>
  )
}
