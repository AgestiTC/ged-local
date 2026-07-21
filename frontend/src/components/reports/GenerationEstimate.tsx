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
// ⚠️ Table volontairement limitée aux modèles RÉELLEMENT installés : y laisser des modèles
// supprimés (mixtral/mistral) ne servait à rien et entretenait la confusion (bug « mixtral »).
// À terme : lire la fenêtre depuis Ollama plutôt que de la figer ici.
const CONTEXTE_MODELE: Record<string, number> = {
  'llama3.1': 128000,
  'qwen3.6-35b': 32000,
  'ministral-3': 32000,
  'qwen2.5vl': 32000,
}
function fenetre(model: string): number {
  const k = (model || '').toLowerCase()
  return CONTEXTE_MODELE[k] ?? CONTEXTE_MODELE[k.split(':')[0]] ?? 8000
}

function fmtMo(o: number) {
  if (o < 1024 * 1024) return `${(o / 1024).toFixed(0)} Ko`
  return `${(o / 1024 / 1024).toFixed(1)} Mo`
}

/**
 * `modelEffectif` = le modèle RÉELLEMENT utilisé : la sélection, ou — en « Auto » (`model === ''`) —
 * le défaut résolu par le backend. Sans lui, l'estimation porterait sur une chaîne vide.
 * `tailleOctets` = taille de ce modèle (Ollama) → sert à juger s'il est lent, **sans** heuristique
 * sur le NOM (l'ancien `startsWith('mixtral')` pointait un modèle supprimé).
 */
export default function GenerationEstimate({
  modelEffectif,
  tailleOctets,
}: {
  modelEffectif: string
  tailleOctets?: number
}) {
  const { documents, selectedIds, metaSelection } = useDocumentStore()
  const { prompt } = useReportStore()
  const model = modelEffectif

  if (selectedIds.size === 0) return null

  // La sélection vient de DEUX sources : la liste chargée (`documents`) ou l'arbre de la page
  // Créer, qui ne charge rien. Se limiter à `documents` affichait « 0 doc · 0 Ko » alors que
  // plusieurs fichiers étaient cochés — on complète donc par `metaSelection`.
  const selDocs = [...selectedIds].map(id =>
    documents.find(d => d.id === id) ?? metaSelection[id]
  ).filter(Boolean) as Array<{ taille_octets?: number; texte_longueur?: number }>
  const octets = selDocs.reduce((s, d) => s + (d.taille_octets || 0), 0)

  // Ce qui part au modèle, c'est le TEXTE EXTRAIT — pas le fichier. Compter les octets du
  // fichier surestimait massivement (2 PDF de 4,9 Mo → « 1,2 M tokens » et une alerte de
  // dépassement, alors que leur texte en fait quelques milliers). On utilise donc le nombre
  // de caractères extraits ; à défaut (document dont on ignore la longueur), on retombe sur
  // la taille du fichier, faute de mieux.
  const caracteres = selDocs.reduce(
    (s, d) => s + (d.texte_longueur ?? (d.taille_octets || 0)), 0,
  )
  const approximatif = selDocs.some(d => d.texte_longueur === undefined)
  // ≈ 4 caractères par token (ordre de grandeur usuel en français).
  const tokens = Math.round((caracteres + prompt.length) / 4)
  const limite = fenetre(model)
  const ratio = tokens / limite
  const tokK = tokens >= 1000 ? `${(tokens / 1000).toFixed(1)} k` : `${tokens}`

  // Bande de temps très grossière — purement indicatif. « Lourd » se déduit de la TAILLE
  // réelle du modèle (> ~20 Go), pas de son nom : un nom en dur devient faux dès qu'on
  // change de modèle (ex. Qwen3.6-35B ≈ 43 Go = lent ; llama3.1 ≈ 4,9 Go = rapide).
  const lourd = (tailleOctets ?? 0) > 20e9
  const tempsBande = tokens < 4000 ? (lourd ? '~1 min' : '~20 s')
    : tokens < 15000 ? (lourd ? '~2–4 min' : '~1 min')
    : (lourd ? '~5 min+' : '~2 min+')

  const trop = ratio > 0.9

  return (
    <div className={`text-xs rounded-lg border px-3 py-2 flex items-start gap-2 ${trop ? 'bg-amber-50 border-amber-200 text-amber-800' : 'bg-gray-50 border-gray-200 text-gray-500'}`}>
      {trop ? <AlertTriangle size={13} className="shrink-0 mt-0.5" /> : <Gauge size={13} className="shrink-0 mt-0.5" />}
      <div>
        <span className="font-medium">Estimation</span> : {selDocs.length} doc{selDocs.length > 1 ? 's' : ''} · {fmtMo(octets)} ·
        {' '}≈ <strong>{tokK} tokens</strong>{approximatif && <span title="Longueur du texte inconnue pour au moins un document : estimation à partir de la taille du fichier, donc surévaluée."> (approx.)</span>} · temps {tempsBande}
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
