/**
 * GenerationGuard — garde-fou pendant la génération d'un rapport (streaming SSE « live »)
 * =======================================================================================
 * Le rapport se génère via un flux SSE lié à l'onglet : fermer l'onglet interrompt
 * l'affichage. Tant qu'une génération est en cours (`isGenerating`), on :
 *   1) affiche un bandeau d'avertissement (visible sur toutes les pages) ;
 *   2) arme un `beforeunload` → le navigateur demande confirmation avant de fermer/recharger.
 * Monté une seule fois dans le layout principal.
 */
import { useEffect } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useReportStore } from '../../stores/reportStore'

export default function GenerationGuard() {
  const isGenerating = useReportStore(s => s.isGenerating)

  useEffect(() => {
    if (!isGenerating) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = '' // requis par certains navigateurs pour déclencher la confirmation
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isGenerating])

  if (!isGenerating) return null

  return (
    <div className="fixed bottom-3 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 rounded-full
                    bg-amber-500 text-white text-xs font-medium px-4 py-2 shadow-lg">
      <AlertTriangle size={14} className="shrink-0" />
      Rapport en cours d'écriture — ne fermez pas l'onglet
    </div>
  )
}
