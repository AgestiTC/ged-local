/**
 * Page Rapports — Layout 3 colonnes
 * Gauche  : sélection fichiers + drag & drop
 * Centre  : mode sortie + modèle + template/groupe + prompt
 * Droite  : résultat / progression comparatif
 */
import { useState } from 'react'
import { useDocumentStore } from '../stores/documentStore'
import { useReportStore } from '../stores/reportStore'
import DropZone from '../components/files/DropZone'
import FileExplorer from '../components/files/FileExplorer'
import PromptEditor from '../components/reports/PromptEditor'
import ModelSelector from '../components/reports/ModelSelector'
import OutputMode from '../components/reports/OutputMode'
import TemplateUpload from '../components/reports/TemplateUpload'
import GenerateButton from '../components/reports/GenerateButton'
import GenerationEstimate from '../components/reports/GenerationEstimate'
import ReportPreview from '../components/reports/ReportPreview'
import GroupBuilder from '../components/reports/GroupBuilder'
import CompareProgress from '../components/reports/CompareProgress'
import { compareApi } from '../api'
import { useToast } from '../components/common/Toast'
import type { GroupeComparatif } from '../types'

export default function ReportsPage() {
  const { selectedIds } = useDocumentStore()
  const { outputMode, model } = useReportStore()
  const toast = useToast()

  const [selectedTemplateId, setSelectedTemplateId] = useState<string | undefined>()

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

  return (
    <div className="flex h-full gap-3 p-3 overflow-hidden">

      {/* ── Colonne gauche : fichiers ───────────────────────── */}
      <aside className="w-64 shrink-0 flex flex-col gap-3">
        <div className="bg-white rounded-lg border border-gray-200 p-3">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Importer</h2>
          <DropZone />
        </div>
        <div className="flex-1 bg-white rounded-lg border border-gray-200 p-3 min-h-0 overflow-hidden flex flex-col">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 shrink-0">
            Documents indexés
            {selectedIds.size > 0 && !isComparatif && (
              <span className="ml-1.5 text-blue-600">({selectedIds.size} sélectionné{selectedIds.size > 1 ? 's' : ''})</span>
            )}
          </h2>
          <div className="flex-1 min-h-0 overflow-hidden">
            <FileExplorer />
          </div>
        </div>
      </aside>

      {/* ── Colonne centrale : configuration ───────────────── */}
      <main className="flex-1 flex flex-col gap-3 min-w-0">
        <div className="flex-1 bg-white rounded-lg border border-gray-200 p-4 flex flex-col gap-4 overflow-auto">

          {/* Mode de sortie */}
          <div>
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Mode</h2>
            <OutputMode />
          </div>

          {/* Modèle */}
          <div>
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Modèle</h2>
            <ModelSelector />
          </div>

          {/* ── MODE COMPARATIF ── */}
          {isComparatif && (
            <>
              <div>
                <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Template Excel</h2>
                <TemplateUpload
                  selectedTemplateId={selectedTemplateId}
                  onSelect={setSelectedTemplateId}
                />
              </div>

              <div className="flex-1 flex flex-col min-h-0">
                <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Candidats / Sociétés
                </h2>
                <div className="flex-1 overflow-auto">
                  <GroupBuilder groupes={groupes} onChange={setGroupes} />
                </div>
              </div>

              <div>
                <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Instructions (optionnel)
                </h2>
                <textarea
                  value={instructions}
                  onChange={e => setInstructions(e.target.value)}
                  placeholder="Ex : Mettre en valeur les points différenciants, utiliser des chiffres précis…"
                  rows={2}
                  className="w-full text-xs border border-gray-200 rounded-lg p-2.5 resize-none outline-none focus:border-blue-300 text-gray-700 placeholder-gray-400"
                />
              </div>
            </>
          )}

          {/* ── AUTRES MODES ── */}
          {!isComparatif && (
            <>
              {outputMode === 'remplir_template' && (
                <div>
                  <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Template DOCX</h2>
                  <TemplateUpload
                    selectedTemplateId={selectedTemplateId}
                    onSelect={setSelectedTemplateId}
                  />
                </div>
              )}
              <div className="flex-1 flex flex-col min-h-0">
                <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  {outputMode === 'classement' ? 'Critères de classement' : 'Instructions'}
                </h2>
                <PromptEditor />
              </div>
            </>
          )}
        </div>

        {/* Bouton Générer */}
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
      </main>

      {/* ── Colonne droite : résultat / progression ─────────── */}
      <aside className="w-[400px] shrink-0 bg-white rounded-lg border border-gray-200 p-4 flex flex-col overflow-hidden">
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
