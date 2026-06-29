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
import AssistantInput from '../components/reports/AssistantInput'
import Step from '../components/reports/Step'
import GroupBuilder from '../components/reports/GroupBuilder'
import ResultPanel from '../components/reports/ResultPanel'
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
  const isWiki = outputMode === 'wiki'

  // Numérotation dynamique des étapes (dépend du mode)
  let stepNum = 0
  const num = () => ++stepNum

  // Étapes « Documents » et « Sujet / Instructions » extraites en sous-rendus pour pouvoir les
  // RÉORDONNER : en mode wiki, le sujet du tuto passe AVANT les documents (optionnels).
  // num() est appelé à l'invocation → la numérotation suit l'ordre de rendu.
  const renderDocsStep = () => (
    <Step
      n={num()}
      title={isWiki ? 'Documents sources (optionnel)' : 'Quels documents ?'}
      hint={isWiki
        ? (selectedIds.size > 0
            ? `${selectedIds.size} document${selectedIds.size > 1 ? 's' : ''} comme appui.`
            : 'Facultatif — appuie-toi sur des documents indexés, ou rédige le tuto from scratch.')
        : (selectedIds.size > 0
            ? `${selectedIds.size} document${selectedIds.size > 1 ? 's' : ''} sélectionné${selectedIds.size > 1 ? 's' : ''}.`
            : 'Coche des fichiers — ou laisse l\'Assistant les proposer.')}
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
        : <AssistantInput />}
    </Step>
  )

  const renderPromptStep = () => (
    <Step
      n={num()}
      title={isWiki ? 'Sujet / consignes du tuto' : outputMode === 'classement' ? 'Critères de classement' : 'Instructions'}
      hint={isWiki
        ? 'Décris le tuto à rédiger — l\'IA produit le Markdown (publiable sur le wiki).'
        : 'Décris ce que l\'IA doit produire à partir des documents.'}
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
  )

  return (
    <div className="flex flex-col h-full gap-3 p-3 overflow-hidden">

      {/* ① Que veux-tu produire ? — barre pleine largeur */}
      <Step n={num()} title="Que veux-tu produire ?" hint="Choisis la destination — la suite s'adapte." last>
        <OutputMode />
      </Step>

      {/* Corps : configuration (gauche) + résultat (droite) */}
      <div className="flex gap-4 flex-1 min-h-0 overflow-hidden">

        {/* ── Colonne config : parcours guidé ─────────────────── */}
        <section className="w-[460px] shrink-0 flex flex-col gap-3 overflow-y-auto pr-1 pb-2">

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
            {/* Bandeau d'aide en mode « Tuto wiki » */}
            {isWiki && (
              <div className="rounded-lg bg-purple-50 border border-purple-100 p-3 text-xs text-purple-800 leading-relaxed">
                <strong>📖 Tuto wiki</strong> — décris ton tuto dans <strong>« Sujet / consignes »</strong>{' '}
                (les documents sont optionnels), puis <strong>Générer</strong>. Le résultat est éditable, et
                la <strong>publication sur le wiki reste manuelle</strong> (bouton « Publier sur le wiki »).
              </div>
            )}

            {/* Template DOCX (mode « remplir un template » uniquement) */}
            {isTemplate && (
              <Step n={num()} title="Template DOCX" hint="Le modèle Word à remplir automatiquement.">
                <TemplateUpload selectedTemplateId={selectedTemplateId} onSelect={setSelectedTemplateId} />
              </Step>
            )}

            {/* En wiki : Sujet (②) AVANT Documents (③). Sinon : Documents puis Instructions. */}
            {isWiki ? (
              <>
                {renderPromptStep()}
                {renderDocsStep()}
              </>
            ) : (
              <>
                {renderDocsStep()}
                {renderPromptStep()}
              </>
            )}
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

        {/* ── Colonne droite : panneau « Résultat » dynamique unifié ── */}
        <ResultPanel
          isComparatif={isComparatif}
          compareJobId={compareJobId}
          groupeNoms={groupes.map(g => g.nom)}
          onComparatifComplete={() => {
            setIsComparing(false)
            toast.success('Rapport comparatif généré et téléchargé !')
          }}
          onComparatifError={(msg) => {
            setIsComparing(false)
            setCompareJobId(null)
            toast.error(msg)
          }}
        />

      </div>
    </div>
  )
}
