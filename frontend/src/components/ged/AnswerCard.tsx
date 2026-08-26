/**
 * AnswerCard — Réponse de l'Assistant « Poser une question » (E8)
 * ===============================================================
 * Affiche la réponse textuelle ANCRÉE (composée côté backend par gabarit, sans invention) +
 * un badge de confiance + les documents justificatifs. Si aucun fait n'est ancré
 * (`approchant`), on assume un repli honnête : « je n'ai pas trouvé » + documents approchants.
 */
import { useState, type ReactNode } from 'react'
import { Brain, ChevronDown, ChevronRight, FileText, Loader2, Search, SearchX } from 'lucide-react'
import type { QAReponse, QADocument, Confiance } from '../../api'

// Tranches de pertinence (mêmes seuils que le classement de la recherche GED) pour ranger les
// documents APPROCHANTS quand aucune réponse n'est ancrée → sections repliables.
const TRANCHES = [
  { key: 'haut', label: '🟢 Assez proche · 80–100 %', min: 80 },
  { key: 'moyen', label: '🟡 Moyennement proche · 50–80 %', min: 50 },
  { key: 'faible', label: '🟠 Faiblement proche · 25–50 %', min: 25 },
  { key: 'tres_faible', label: '⚪ Très faible · < 25 %', min: 0 },
]
const pct = (d: QADocument) => d.pertinence ?? 0

const CONF_STYLE: Record<Confiance, string> = {
  'Élevée': 'bg-green-50 text-green-700 border-green-200',
  'Moyenne': 'bg-amber-50 text-amber-700 border-amber-200',
  'Faible': 'bg-gray-100 text-gray-500 border-gray-200',
}

/** Documents APPROCHANTS classés par tranche de pertinence, en sections repliables. */
function ApprochantsGroupes({ docs, carteDoc, onOpen }: {
  docs: QADocument[]
  carteDoc?: (d: QADocument) => ReactNode
  onOpen?: (id: string) => void
}) {
  // Répartition dans les tranches (chaque doc dans la 1ʳᵉ tranche dont il dépasse le seuil).
  const groupes = TRANCHES.map(t => ({
    ...t, items: docs.filter(d => pct(d) >= t.min && !TRANCHES.some(u => u.min > t.min && pct(d) >= u.min)),
  })).filter(g => g.items.length > 0)

  // Par défaut : seule la MEILLEURE tranche non vide est dépliée (les autres repliées).
  const [replie, setReplie] = useState<Set<string>>(() => new Set(groupes.slice(1).map(g => g.key)))
  const basculer = (k: string) => setReplie(s => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })

  return (
    <div className="mt-3 space-y-2">
      {groupes.map(g => {
        const ouvert = !replie.has(g.key)
        return (
          <div key={g.key} className="border border-gray-100 rounded-lg overflow-hidden">
            <button type="button" onClick={() => basculer(g.key)}
              className="w-full flex items-center gap-1.5 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50">
              {ouvert ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <span className="font-medium">{g.label}</span>
              <span className="text-xs text-gray-400">· {g.items.length}</span>
            </button>
            {ouvert && (
              <div className="p-2 space-y-2 bg-gray-50/50">
                {carteDoc
                  ? g.items.map(d => carteDoc(d))
                  : g.items.map(d => (
                      <button key={d.id} type="button" onClick={() => onOpen?.(d.id)}
                        className="w-full flex items-center gap-2 text-left px-2.5 py-1.5 rounded-md bg-white border border-gray-100 hover:border-violet-200">
                        <FileText size={14} className="text-gray-400 shrink-0" />
                        <span className="text-sm text-gray-700 truncate">{d.nom}</span>
                        <span className="ml-auto text-xs text-gray-400">{pct(d)} %</span>
                      </button>
                    ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
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
  answer, loading, query, onOpen, carteDoc,
}: {
  answer: QAReponse | null
  loading: boolean
  query: string
  onOpen?: (id: string) => void
  /** Rendu d'un document justificatif (fourni par la page → mêmes pictogrammes Aperçu/Fiche/… que les autres cartes). */
  carteDoc?: (d: QADocument) => ReactNode
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
    <div className="mt-3 space-y-2">
      <p className="text-xs font-medium text-gray-500">
        {answer.approchant ? 'Documents approchants' : `${docs.length} document${docs.length > 1 ? 's' : ''} justificatif${docs.length > 1 ? 's' : ''}`}
      </p>
      {/* Si la page fournit son rendu de carte (pictogrammes Aperçu/Fiche/Télécharger), on l'utilise ;
          sinon repli sur une ligne simple cliquable. */}
      {carteDoc
        ? <div className="space-y-2">{docs.map(d => carteDoc(d))}</div>
        : docs.map(d => (
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
    // Vraiment aucun document approchant → message « non trouvé » net.
    if (docs.length === 0) {
      return (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="flex items-center gap-2.5">
            <SearchX size={20} className="text-gray-400 shrink-0" />
            <div>
              <p className="text-sm font-medium text-gray-700">Aucun document trouvé pour « {query} ».</p>
              <p className="text-xs text-gray-400 mt-0.5">
                Aucune fiche de paie, contrat ou document rattaché à cette demande n'est présent dans la GED.
              </p>
            </div>
          </div>
        </div>
      )
    }
    // Distinguer une vraie QUESTION (employeur, durée…) d'une simple recherche par NOM / mot-clé :
    // pour un nom, il n'y a pas de « réponse » attendue → on présente positivement les documents liés,
    // sans parler d'« OCR insuffisant » (trompeur quand on trouve des documents très pertinents).
    const estQuestion = answer.intent?.intent === 'employeur_a_date' || answer.intent?.intent === 'duree_emploi'
    const maxPert = docs.reduce((mx, d) => Math.max(mx, d.pertinence ?? 0), 0)

    return (
      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex items-start gap-2.5">
          {estQuestion
            ? <SearchX size={20} className="text-gray-400 mt-0.5 shrink-0" />
            : <Search size={20} className="text-violet-400 mt-0.5 shrink-0" />}
          <div className="flex-1">
            {estQuestion ? (
              <>
                <p className="text-sm font-medium text-gray-700">
                  Je n'ai pas trouvé de réponse directe à « {query} ».
                </p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {maxPert < 50
                    ? <>Aucune information exploitable (pièce non indexée, ou OCR insuffisant). Voici les documents <strong>approchants</strong> :</>
                    : <>Voici les documents <strong>en lien</strong>, classés par pertinence :</>}
                </p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium text-gray-700">
                  Documents en lien avec « {query} »
                </p>
                <p className="text-xs text-gray-400 mt-0.5">
                  « {query} » est un nom / mot-clé, pas une question. Voici les documents où il apparaît,
                  classés par pertinence :
                </p>
              </>
            )}
            <ApprochantsGroupes docs={docs} carteDoc={carteDoc} onOpen={onOpen} />
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
