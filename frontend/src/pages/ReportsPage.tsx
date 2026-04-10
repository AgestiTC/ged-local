/**
 * Page Rapports — Génération de rapports à partir de documents
 * Layout 3 colonnes : fichiers | config | résultat
 * TODO Phase 2 : implémenter les composants
 */
export default function ReportsPage() {
  return (
    <div className="flex h-full gap-4 p-4">
      {/* Colonne gauche : sélection fichiers + drag & drop */}
      <aside className="w-72 shrink-0 bg-white rounded-lg border border-gray-200 p-4">
        <h2 className="font-semibold text-gray-700 mb-3">Documents</h2>
        <p className="text-sm text-gray-400">TODO Phase 2 — FileExplorer + DropZone</p>
      </aside>

      {/* Colonne centrale : prompt + config */}
      <main className="flex-1 bg-white rounded-lg border border-gray-200 p-4">
        <h2 className="font-semibold text-gray-700 mb-3">Configuration</h2>
        <p className="text-sm text-gray-400">TODO Phase 2 — PromptEditor + ModelSelector</p>
      </main>

      {/* Colonne droite : résultat */}
      <aside className="w-96 shrink-0 bg-white rounded-lg border border-gray-200 p-4">
        <h2 className="font-semibold text-gray-700 mb-3">Résultat</h2>
        <p className="text-sm text-gray-400">TODO Phase 2 — ReportPreview</p>
      </aside>
    </div>
  )
}
