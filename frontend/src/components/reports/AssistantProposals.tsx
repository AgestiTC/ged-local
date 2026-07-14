/**
 * AssistantProposals — propositions de l'Assistant, affichées dans « Résultat »
 * =============================================================================
 * Liste les pièces déduites par l'IA et, pour chacune, les fichiers connus de la
 * GED. Cocher un fichier l'ajoute à la sélection utilisée pour le rapport.
 */
import { useEffect, useState } from 'react'
import { FileText, Check, FolderOpen, Loader2, Eye } from 'lucide-react'
import { clsx } from 'clsx'
import { useReportAssistantStore } from '../../stores/reportAssistantStore'
import { useDocumentStore } from '../../stores/documentStore'
import DocumentPreview from '../ged/DocumentPreview'
import type { Document } from '../../types'

export default function AssistantProposals() {
  const { pieces, loading, besoin } = useReportAssistantStore()
  const { selectDocument, deselectDocument, isSelected } = useDocumentStore()
  // Aperçu d'une pièce proposée (même modale que la GED) → pouvoir OUVRIR la carte
  // pour décider de l'inclure, sans quitter l'assistant.
  const [preview, setPreview] = useState<Document | null>(null)

  // Compteur de secondes pendant la recherche (l'attente paraît intentionnelle, pas bloquée)
  const [sec, setSec] = useState(0)
  useEffect(() => {
    if (!loading) { setSec(0); return }
    const t = setInterval(() => setSec(s => s + 1), 1000)
    return () => clearInterval(t)
  }, [loading])

  const toggle = (id: string) => { isSelected(id) ? deselectDocument(id) : selectDocument(id) }

  if (loading) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-2 px-6 text-center">
        <Loader2 size={22} className="animate-spin text-blue-500" />
        <p className="text-sm text-gray-600">
          {sec < 3 ? 'Déduction des pièces attendues…' : 'Recherche des fichiers correspondants…'}
        </p>
        <p className="text-xs">L'IA réfléchit ({sec} s) — recherche sémantique sur tous les indexés.</p>
      </div>
    )
  }

  if (!pieces) return null

  const total = pieces.reduce((n, p) => n + p.documents.length, 0)

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Pour « <strong>{besoin}</strong> » — {total} fichier{total > 1 ? 's' : ''} proposé{total > 1 ? 's' : ''}.
        Coche ceux à inclure, puis lance la génération à gauche.
      </p>

      {pieces.map((p, i) => (
        <div key={i} className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-3 py-1.5 bg-gray-50 text-xs font-medium text-gray-700 flex items-center gap-1.5">
            <FolderOpen size={13} className="text-amber-500" /> {p.libelle}
            <span className="text-gray-400">· {p.documents.length} proposé{p.documents.length > 1 ? 's' : ''}</span>
          </div>
          {p.documents.length === 0 ? (
            <p className="px-3 py-2 text-xs text-gray-400">Aucun fichier connu.</p>
          ) : (
            <ul className="divide-y divide-gray-50">
              {p.documents.map(d => {
                const sel = isSelected(d.id)
                return (
                  <li key={d.id} className={clsx('flex items-center gap-1 pr-2 hover:bg-blue-50/50', sel && 'bg-blue-50')}>
                    {/* Zone cochable (coche + nom) */}
                    <button type="button" onClick={() => toggle(d.id)}
                      className="flex-1 min-w-0 flex items-center gap-2 px-3 py-1.5 text-left text-sm">
                      <span className={clsx('w-4 h-4 rounded border flex items-center justify-center shrink-0',
                        sel ? 'bg-blue-600 border-blue-600 text-white' : 'border-gray-300')}>
                        {sel && <Check size={12} />}
                      </span>
                      <FileText size={13} className="text-gray-400 shrink-0" />
                      <span className="flex-1 truncate">{d.nom}</span>
                    </button>
                    <span className="text-xs text-gray-300 shrink-0">{(d.score * 100).toFixed(0)}%</span>
                    {/* Ouvrir l'aperçu du fichier (décider sans quitter l'assistant) */}
                    <button type="button" title="Aperçu du fichier"
                      onClick={() => setPreview({ id: d.id, nom: d.nom, extension: d.extension, chemin: '', chemin_copie: '' } as Document)}
                      className="flex items-center gap-1 text-xs px-1.5 py-1 text-blue-600 hover:bg-blue-100 rounded shrink-0">
                      <Eye size={13} />
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      ))}

      <p className="text-[11px] text-gray-400">
        💡 Pour une <strong>synthèse</strong> d'un groupe : coche les documents puis utilise le mode
        <strong> « Rapport rédigé »</strong>.
      </p>

      {/* Aperçu du fichier proposé (overlay) */}
      {preview && <DocumentPreview doc={preview} onClose={() => setPreview(null)} />}
    </div>
  )
}
