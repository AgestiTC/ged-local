/**
 * ReportAssistant — assistant de constitution de dossier (1a)
 * ==========================================================
 * L'utilisateur décrit un besoin (« dossier de location »…) ; l'IA déduit les
 * pièces attendues et propose, pour chacune, les fichiers connus de la GED. On
 * peut cocher les fichiers → ils rejoignent la sélection utilisée pour le rapport.
 */
import { useState } from 'react'
import { Sparkles, Loader2, FileText, Check, FolderOpen } from 'lucide-react'
import { clsx } from 'clsx'
import { assistantApi, type PieceProposee } from '../../api'
import { useDocumentStore } from '../../stores/documentStore'
import { useToast } from '../common/Toast'

export default function ReportAssistant() {
  const toast = useToast()
  const { selectDocument, deselectDocument, isSelected } = useDocumentStore()
  const [besoin, setBesoin] = useState('')
  const [loading, setLoading] = useState(false)
  const [pieces, setPieces] = useState<PieceProposee[] | null>(null)

  const proposer = async () => {
    if (besoin.trim().length < 3) return
    setLoading(true); setPieces(null)
    try {
      const r = await assistantApi.pieces(besoin.trim())
      setPieces(r.pieces)
      const total = r.pieces.reduce((n, p) => n + p.documents.length, 0)
      if (total === 0) toast.info('Aucun fichier connu ne correspond — affine le besoin.')
    } catch {
      toast.error('Assistant indisponible (Ollama ?)')
    } finally { setLoading(false) }
  }

  const toggle = (id: string) => { isSelected(id) ? deselectDocument(id) : selectDocument(id) }

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Décris ton besoin : l'IA déduit les <strong>pièces attendues</strong> et propose les fichiers
        connus. Coche-les pour les ajouter à la sélection du rapport.
      </p>
      <div className="flex gap-2">
        <textarea
          value={besoin}
          onChange={e => setBesoin(e.target.value)}
          placeholder="Ex : « j'ai besoin de documents pour un dossier de location », « monter un dossier d'appel d'offres »…"
          rows={2}
          className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
        <button type="button" onClick={proposer} disabled={loading || besoin.trim().length < 3}
          className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-40 self-start">
          {loading ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
          {loading ? 'Recherche…' : 'Proposer'}
        </button>
      </div>

      {pieces && (
        <div className="space-y-2">
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
                      <li key={d.id}>
                        <button type="button" onClick={() => toggle(d.id)}
                          className={clsx('w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-blue-50/50',
                            sel && 'bg-blue-50')}>
                          <span className={clsx('w-4 h-4 rounded border flex items-center justify-center shrink-0',
                            sel ? 'bg-blue-600 border-blue-600 text-white' : 'border-gray-300')}>
                            {sel && <Check size={12} />}
                          </span>
                          <FileText size={13} className="text-gray-400 shrink-0" />
                          <span className="flex-1 truncate">{d.nom}</span>
                          <span className="text-xs text-gray-300 shrink-0">{(d.score * 100).toFixed(0)}%</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          ))}
          <p className="text-[11px] text-gray-400">
            💡 Pour une <strong>synthèse</strong> d'un groupe : sélectionne des documents puis utilise le
            mode <strong>« Rapport libre »</strong> ci-dessous.
          </p>
        </div>
      )}
    </div>
  )
}
