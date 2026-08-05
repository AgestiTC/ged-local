/**
 * AnswerCard — Réponse de l'Assistant « Poser une question » (E8)
 * ===============================================================
 * Affiche la réponse textuelle ANCRÉE (composée côté backend par gabarit, sans invention) +
 * un badge de confiance + les documents justificatifs. Si aucun fait n'est ancré
 * (`approchant`), on assume un repli honnête : « je n'ai pas trouvé » + documents approchants.
 */
import { Brain, FileText, Loader2, SearchX } from 'lucide-react'
import type { QAReponse, Confiance } from '../../api'

const CONF_STYLE: Record<Confiance, string> = {
  'Élevée': 'bg-green-50 text-green-700 border-green-200',
  'Moyenne': 'bg-amber-50 text-amber-700 border-amber-200',
  'Faible': 'bg-gray-100 text-gray-500 border-gray-200',
}

/** Rendu minimal du gras `**…**` (la réponse backend n'utilise que ça). */
function RichText({ texte }: { texte: string }) {
  const bouts = texte.split(/(\*\*[^*]+\*\*)/g)
  return (
    <>
      {bouts.map((b, i) =>
        b.startsWith('**') && b.endsWith('**')
          ? <strong key={i} className="font-semibold text-gray-900">{b.slice(2, -2)}</strong>
          : <span key={i}>{b}</span>,
      )}
    </>
  )
}

export default function AnswerCard({
  answer, loading, query, onOpen,
}: {
  answer: QAReponse | null
  loading: boolean
  query: string
  onOpen?: (id: string) => void
}) {
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-gray-400 gap-2 text-center">
        <Loader2 size={22} className="animate-spin text-violet-500" />
        <p className="text-sm text-gray-600">L'IA lit les documents et compose une réponse…</p>
        <p className="text-xs">Compréhension → recherche ciblée → lecture des pièces → synthèse.</p>
      </div>
    )
  }

  if (!answer) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-gray-300 gap-3 text-center">
        <Brain size={44} strokeWidth={1} className="text-violet-300" />
        <p className="text-sm text-gray-500">Pose une question en langage naturel</p>
        <p className="text-xs">Ex. « Où travaillait Thomas en juillet 2018 ? » · « Combien de temps chez LApp Muller ? »</p>
      </div>
    )
  }

  const docs = answer.documents || []
  const listeDocs = docs.length > 0 && (
    <div className="mt-3 space-y-1.5">
      <p className="text-xs font-medium text-gray-500">
        {answer.approchant ? 'Documents approchants' : `${docs.length} document${docs.length > 1 ? 's' : ''} justificatif${docs.length > 1 ? 's' : ''}`}
      </p>
      {docs.map(d => (
        <button key={d.id} type="button" onClick={() => onOpen?.(d.id)}
          className="w-full flex items-center gap-2 text-left px-2.5 py-1.5 rounded-md border border-gray-100 hover:border-violet-200 hover:bg-violet-50/40 transition-colors">
          <FileText size={14} className="text-gray-400 shrink-0" />
          <span className="text-sm text-gray-700 truncate">{d.nom}</span>
          <span className="ml-auto flex items-center gap-2 shrink-0 text-xs text-gray-400">
            {d.employeur && <span className="text-gray-500">{d.employeur}</span>}
            {d.periode && <span className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{d.periode}</span>}
            <span className="uppercase">{d.extension}</span>
          </span>
        </button>
      ))}
    </div>
  )

  // Repli honnête : aucun fait ancré.
  if (answer.approchant || !answer.reponse) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex items-start gap-2.5">
          <SearchX size={20} className="text-gray-400 mt-0.5 shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-medium text-gray-700">
              Je n'ai pas trouvé de document permettant de répondre à « {query} ».
            </p>
            <p className="text-xs text-gray-400 mt-0.5">
              Aucune information ancrée dans un document (souvent : la pièce n'est pas indexée, ou l'OCR
              n'a rien rendu d'exploitable). Voici les documents les plus proches :
            </p>
            {listeDocs}
          </div>
        </div>
      </div>
    )
  }

  // Réponse ancrée.
  return (
    <div className="rounded-xl border border-violet-200 bg-gradient-to-br from-violet-50/60 to-white p-4">
      <div className="flex items-start gap-2.5">
        <Brain size={20} className="text-violet-500 mt-0.5 shrink-0" />
        <div className="flex-1">
          <div className="flex items-start justify-between gap-3">
            <p className="text-[15px] leading-relaxed text-gray-800"><RichText texte={answer.reponse} /></p>
            <span className={`shrink-0 text-[11px] px-2 py-0.5 rounded-full border ${CONF_STYLE[answer.confiance]}`}
              title="Niveau de confiance selon le nombre de documents concordants">
              {answer.confiance}
            </span>
          </div>
          {listeDocs}
        </div>
      </div>
    </div>
  )
}
