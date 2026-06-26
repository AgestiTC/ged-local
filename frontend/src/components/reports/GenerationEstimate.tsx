/**
 * GenerationEstimate — Estimation du contexte avant génération
 * ============================================================
 * Indicateur approximatif : nombre de documents, volume, tokens estimés et
 * avertissement si le contexte risque de dépasser la fenêtre du modèle.
 * Heuristique volontairement simple (≈ 4 octets/token) — affiché comme estimation.
 */
import { AlertTriangle, Gauge } from 'lucide-react'
import { useDocumentStore } from '../../stores/documentStore'
import { useReportStore } from '../../stores/reportStore'

// Fenêtre de contexte approximative par modèle (tokens). Défaut prudent.
const CONTEXTE_MODELE: Record<string, number> = {
  mixtral: 32000, 'mixtral:latest': 32000,
  llama3: 8000, 'llama3.1': 128000, 'llama3.1:latest': 128000,
  mistral: 8000, 'mistral:latest': 8000,
}
function fenetre(model: string): number {
  return CONTEXTE_MODELE[model] ?? CONTEXTE_MODELE[model?.split(':')[0]] ?? 8000
}

function fmtMo(o: number) {
  if (o < 1024 * 1024) return `${(o / 1024).toFixed(0)} Ko`
  return `${(o / 1024 / 1024).toFixed(1)} Mo`
}

export default function GenerationEstimate() {
  const { documents, selectedIds } = useDocumentStore()
  const { prompt, model } = useReportStore()

  if (selectedIds.size === 0) return null

  const selDocs = documents.filter(d => selectedIds.has(d.id))
  const octets = selDocs.reduce((s, d) => s + (d.taille_octets || 0), 0)
  // ≈ 4 octets par token (approximation grossière, surtout pour les binaires type PDF)
  const tokens = Math.round((octets + prompt.length) / 4)
  const limite = fenetre(model)
  const ratio = tokens / limite
  const tokK = tokens >= 1000 ? `${(tokens / 1000).toFixed(1)} k` : `${tokens}`

  // Bande de temps très grossière (mixtral est lent) — purement indicatif
  const lourd = model.startsWith('mixtral')
  const tempsBande = tokens < 4000 ? (lourd ? '~1 min' : '~20 s')
    : tokens < 15000 ? (lourd ? '~2–4 min' : '~1 min')
    : (lourd ? '~5 min+' : '~2 min+')

  const trop = ratio > 0.9

  return (
    <div className={`text-xs rounded-lg border px-3 py-2 flex items-start gap-2 ${trop ? 'bg-amber-50 border-amber-200 text-amber-800' : 'bg-gray-50 border-gray-200 text-gray-500'}`}>
      {trop ? <AlertTriangle size={13} className="shrink-0 mt-0.5" /> : <Gauge size={13} className="shrink-0 mt-0.5" />}
      <div>
        <span className="font-medium">Estimation</span> : {selDocs.length} doc{selDocs.length > 1 ? 's' : ''} · {fmtMo(octets)} ·
        {' '}≈ <strong>{tokK} tokens</strong> · temps {tempsBande}
        {trop && (
          <div className="mt-0.5">
            ⚠ Contexte proche/au-delà de la fenêtre du modèle (~{(limite / 1000).toFixed(0)} k) — le contenu sera tronqué.
            Réduisez la sélection ou utilisez un modèle à plus grand contexte.
          </div>
        )}
      </div>
    </div>
  )
}
