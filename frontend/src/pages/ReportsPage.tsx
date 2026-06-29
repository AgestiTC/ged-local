/**
 * Page Rapports — Parcours guidé (stepper)
 * ========================================
 * Colonne gauche : étapes numérotées (1 Quoi produire · 2 Documents · 3 Instructions · 4 Générer).
 * Seules les étapes pertinentes pour le mode choisi sont affichées.
 * Colonne droite  : résultat (ou progression du comparatif), en grand.
 */
import { useState } from 'react'
import { useDocumentStore } from '../stores/documentStore'
import { useReportStore } from '../stores/reportStore'
import FileExplorer from '../components/files/FileExplorer'
import PromptEditor from '../components/reports/PromptEditor'
import ModelSelector from '../components/reports/ModelSelector'
import OutputMode from '../components/reports/OutputMode'
import TemplateUpload from '../components/reports/TemplateUpload'
import GenerateButton from '../components/reports/GenerateButton'
import GenerationEstimate from '../components/reports/GenerationEstimate'
import ReportAssistant from '../components/reports/ReportAssistant'
import ReportPreview from '../components/reports/ReportPreview'
import Step from '../components/reports/Step'
import GroupBuilder from '../components/reports/GroupBuilder'
import CompareProgress from '../components/reports/CompareProgress'
import { FolderSearch, Sparkles, Settings2, ChevronDown } from 'lucide-react'
import { clsx } from 'clsx'
import { compareApi } from '../api'
import { useToast } from '../components/common/Toast'
import type { GroupeComparatif } from '../types'

export default function ReportsPage() {
  const { selectedIds } = useDocumentStore()
  const { outputMode, model } = useReportStore()
  const toast = useToast()

  const [selectedTemplateId, setSelectedTemplateId] = useState<string | undefined>()
  const [docTab, setDocTab] = useState<'parcourir' | 'assistant'>('parcourir')
  const [showModele, setShowModele] = useState(false)

  // État mode comparatif
  const [groupes, setGroupes] = useState<GroupeComparatif[]>([])
  const [compareJobId, setCompareJobId] = useState<string | null>(null)
  const [isComparing, setIsComparing] = useState(false)
  const [instructions, setInstructions] = useState('')

  const lancerComparaison = async () => {
    if (!selectedTemplateId) { toast.error('Sélectionnez un template Excel'); return }
    if (groupes.length < 2) { toast.error('Ajoutez au moins 2 candidats / sociétés'); return }
    const invalides = groupes.filter(g => !g.nom.trim() || g.document_ids.length === 0)
    if (invalides.length > 0) { toast.error('Chaque groupe doit avoir un nom et au moins un document'); return }

    setIsComparing(true)
    setCompareJobId(null)
    try {
      const res = await compareApi.start({
        groupes: groupes.map(g => ({ nom: g.nom, document_ids: g.document_ids })),
        template_id: selectedTemplateId,
        model,
        instructions: instructions.trim() || undefined,
      })
      setCompareJobId(res.job_id)
    } catch {
      toast.error('Erreur lancement comparaison')
      setIsComparing(false)
    }
  }

  const isComparatif = outputMode === 'comparatif'
  const isTemplate = outputMode === 'remplir_template'

  // Numérotation dynamique des étapes (dépend du mode)
  let stepNum = 0
  const num = () => ++stepNum

  return (
    <div className="flex h-full gap-4 p-3 overflow-hidden">

      {/* ── Colonne config : parcours guidé ─────────────────── */}
      <section className="w-[460px] shrink-0 flex flex-col gap-3 overflow-y-auto pr-1 pb-2">

        {/* ① Que veux-tu produire ? */}
        <Step n={num()} title="Que veux-tu produire ?" hint="Choisis le type de sortie — la suite s'adapte.">
          <OutputMode />
        </Step>

        {isComparatif ? (
          <>
            {/* ② Template Excel */}
            <Step n={num()} title="Template Excel" hint="Le tableau de comparaison à remplir.">
              <TemplateUpload selectedTemplateId={selectedTemplateId} onSelect={setSelectedTemplateId} />
            </Step>

            {/* ③ Candidats / Sociétés */}
            <Step n={num()} title="Candidats / Sociétés" hint="Un groupe de documents par candidat à comparer.">
              <GroupBuilder groupes={groupes} onChange={setGroupes} />
            </Step>

            {/* ④ Instructions (optionnel) */}
            <Step n={num()} title="Instructions (optionnel)">
              <textarea
                value={instructions}
                onChange={e => setInstructions(e.target.value)}
                placeholder="Ex : Mettre en valeur les points différenciants, utiliser des chiffres précis…"
                rows={2}
                className="w-full text-xs border border-gray-200 rounded-lg p-2.5 resize-none outline-none focus:border-blue-300 text-gray-700 placeholder-gray-400"
              />
            </Step>
          </>
        ) : (
          <>
            {/* Template DOCX (mode « remplir un template » uniquement) */}
            {isTemplate && (
              <Step n={num()} title="Template DOCX" hint="Le modèle Word à remplir automatiquement.">
                <TemplateUpload selectedTemplateId={selectedTemplateId} onSelect={setSelectedTemplateId} />
              </Step>
            )}

            {/* Quels documents ? — Parcourir OU Assistant IA */}
            <Step
              n={num()}
              title="Quels documents ?"
              hint={selectedIds.size > 0
                ? `${selectedIds.size} document${selectedIds.size > 1 ? 's' : ''} sélectionné${selectedIds.size > 1 ? 's' : ''}.`
                : 'Coche des fichiers — ou laisse l\'Assistant les proposer.'}
            >
              {/* Onglets de choix */}
              <div className="flex rounded-lg border border-gray-200 p-0.5 mb-3 bg-gray-50 text-xs">
                {([
                  { key: 'parcourir', label: 'Parcourir', Icon: FolderSearch },
                  { key: 'assistant', label: 'Assistant IA', Icon: Sparkles },
                ] as const).map(({ key, label, Icon }) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setDocTab(key)}
                    className={clsx(
                      'flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md font-medium transition-colors',
                      docTab === key ? 'bg-white text-blue-700 shadow-sm' : 'text-gray-500 hover:text-gray-700',
                    )}
                  >
                    <Icon size={13} /> {label}
                  </button>
                ))}
              </div>

              {docTab === 'parcourir'
                ? <div className="h-[320px]"><FileExplorer /></div>
                : <ReportAssistant />}
            </Step>

            {/* Instructions + Modèle (avancé) */}
            <Step
              n={num()}
              title={outputMode === 'classement' ? 'Critères de classement' : 'Instructions'}
              hint="Décris ce que l'IA doit produire à partir des documents."
            >
              <PromptEditor />

              {/* Modèle — réglage avancé replié par défaut */}
              <button
                type="button"
                onClick={() => setShowModele(v => !v)}
                className="mt-3 flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700"
              >
                <Settings2 size={13} />
                Modèle IA <span className="text-gray-400">({model.split(':')[0]})</span>
                <ChevronDown size={13} className={clsx('transition-transform', showModele && 'rotate-180')} />
              </button>
              {showModele && <div className="mt-2"><ModelSelector /></div>}
            </Step>
          </>
        )}

        {/* Étape finale — Générer */}
        <Step n={num()} title="Générer" accent last>
          {isComparatif ? (
            <button
              type="button"
              onClick={lancerComparaison}
              disabled={isComparing}
              className="w-full py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-semibold rounded-xl text-sm transition-colors"
            >
              {isComparing ? 'Analyse en cours…' : 'Générer le rapport comparatif'}
            </button>
          ) : (
            <div className="flex flex-col gap-2">
              <GenerationEstimate />
              <GenerateButton />
            </div>
          )}
        </Step>
      </section>

      {/* ── Colonne droite : résultat / progression ─────────── */}
      <aside className="flex-1 min-w-0 bg-white rounded-lg border border-gray-200 p-4 flex flex-col overflow-hidden">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3 shrink-0">
          {isComparatif ? 'Progression' : 'Résultat'}
        </h2>
        <div className="flex-1 min-h-0 overflow-auto">
          {isComparatif && compareJobId ? (
            <CompareProgress
              jobId={compareJobId}
              groupeNoms={groupes.map(g => g.nom)}
              onComplete={() => {
                setIsComparing(false)
                toast.success('Rapport comparatif généré et téléchargé !')
              }}
              onError={(msg) => {
                setIsComparing(false)
                setCompareJobId(null)
                toast.error(msg)
              }}
            />
          ) : isComparatif ? (
            <div className="h-full flex flex-col items-center justify-center text-center text-gray-400 gap-2">
              <p className="text-xs">Configurez vos groupes et cliquez sur</p>
              <p className="text-xs font-medium text-gray-500">"Générer le rapport comparatif"</p>
            </div>
          ) : (
            <ReportPreview />
          )}
        </div>
      </aside>

    </div>
  )
}
