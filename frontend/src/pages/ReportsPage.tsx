/**
 * Page Rapports — Layout 3 colonnes
 * Gauche  : sélection fichiers + drag & drop
 * Centre  : mode sortie + modèle + template + prompt
 * Droite  : résultat + export
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
import ReportPreview from '../components/reports/ReportPreview'

export default function ReportsPage() {
  const { selectedIds } = useDocumentStore()
  const { outputMode } = useReportStore()
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | undefined>()

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
            {selectedIds.size > 0 && (
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

          {/* Template (affiché seulement en mode template) */}
          {outputMode === 'remplir_template' && (
            <div>
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Template</h2>
              <TemplateUpload
                selectedTemplateId={selectedTemplateId}
                onSelect={setSelectedTemplateId}
              />
            </div>
          )}

          {/* Instructions */}
          <div className="flex-1 flex flex-col min-h-0">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              {outputMode === 'classement' ? 'Critères de classement' : 'Instructions'}
            </h2>
            <PromptEditor />
          </div>
        </div>

        {/* Bouton Générer */}
        <GenerateButton />
      </main>

      {/* ── Colonne droite : résultat ───────────────────────── */}
      <aside className="w-[400px] shrink-0 bg-white rounded-lg border border-gray-200 p-4 flex flex-col overflow-hidden">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3 shrink-0">Résultat</h2>
        <div className="flex-1 min-h-0 overflow-hidden">
          <ReportPreview />
        </div>
      </aside>

    </div>
  )
}
