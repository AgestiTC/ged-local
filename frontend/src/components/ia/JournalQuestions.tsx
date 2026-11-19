/**
 * JournalQuestions — les questions posées à l'IA sur les documents (plan RAG, étape B2)
 * ====================================================================================
 * Chat appuyé sur la GED (Auto, Toujours) et mode Question de la GED : chaque question est gardée
 * côté serveur avec ses sources (et les passages envoyés), le modèle, la version des prompts, la
 * réponse. Chacun voit et efface les siennes ; `tous` (administrateur, page Journaux) montre celles
 * de tout le monde et règle la conservation.
 */
import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Trash2, MessageSquare, Search, ChevronRight, ChevronDown, Loader2, History, X } from 'lucide-react'
import { clsx } from 'clsx'
import { journalQuestionsApi, systemApi, type OrigineQuestion, type QuestionJournal, type QuestionJournalDetail } from '../../api'
import { confirmerTexte } from '../common/Confirmation'

const CONSERVATION = [
  { j: 0, label: 'Tout garder' }, { j: 365, label: '1 an' },
  { j: 180, label: '6 mois' }, { j: 90, label: '3 mois' }, { j: 30, label: '1 mois' },
]
const STATUT: Record<QuestionJournal['statut'], { label: string; classe: string }> = {
  ok: { label: 'répondue', classe: 'text-green-600' },
  erreur: { label: 'en erreur', classe: 'text-red-600' },
  interrompue: { label: 'interrompue', classe: 'text-amber-600' },
  en_cours: { label: 'en cours', classe: 'text-blue-600' },
}

function quand(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
}
function duree(ms: number | null): string {
  if (ms == null) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`
}

function Detail({ d }: { d: QuestionJournalDetail }) {
  return (
    <div className="ml-6 mb-2 pl-3 border-l-2 border-violet-200 space-y-2 text-xs text-gray-600">
      <p className="whitespace-pre-wrap text-gray-800">{d.question}</p>
      <div>
        <span className="font-medium text-gray-500">Réponse</span>
        <p className="whitespace-pre-wrap mt-0.5">{d.reponse?.trim() || <em className="text-gray-400">aucune</em>}</p>
      </div>
      <div>
        <span className="font-medium text-gray-500">Documents fournis à l'IA</span>
        {d.sources.length === 0 ? <p className="text-gray-400">aucun</p> : (
          <ul className="mt-0.5 space-y-0.5">
            {d.sources.map((s, i) => (
              <li key={`${s.id}-${i}`}>
                {s.nom}
                <span className="text-gray-400">
                  {s.passages?.length ? ` — passage${s.passages.length > 1 ? 's' : ''} n° ${s.passages.join(', ')}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-gray-500">
        {d.modele && <span>Modèle : {d.modele}</span>}
        {typeof d.reglages?.ged_mode === 'string' && <span>GED : {d.reglages.ged_mode}</span>}
        {d.prompts.length > 0 && (
          <span>Prompts : {d.prompts.map(p => `${p.cle} (${p.version ? `v${p.version}` : 'origine'})`).join(' · ')}</span>
        )}
      </div>
    </div>
  )
}

export default function JournalQuestions({ tous = false }: { tous?: boolean }) {
  const [questions, setQuestions] = useState<QuestionJournal[]>([])
  const [total, setTotal] = useState(0)
  const [retention, setRetention] = useState<number | null>(null)
  const [origine, setOrigine] = useState<OrigineQuestion | ''>('')
  const [chargement, setChargement] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [ouverte, setOuverte] = useState<string | null>(null)
  const [detail, setDetail] = useState<QuestionJournalDetail | null>(null)

  const charger = useCallback(async () => {
    setChargement(true); setErreur(null)
    try {
      const r = await journalQuestionsApi.lister({ tous, origine: origine || undefined, limit: 100 })
      setQuestions(r.questions); setTotal(r.total); setRetention(r.retention_jours)
    } catch {
      setErreur('Journal indisponible')
    } finally { setChargement(false) }
  }, [tous, origine])

  useEffect(() => { charger() }, [charger])

  useEffect(() => {
    if (!ouverte) { setDetail(null); return }
    let actif = true
    journalQuestionsApi.detail(ouverte).then(d => { if (actif) setDetail(d) }).catch(() => { if (actif) setDetail(null) })
    return () => { actif = false }
  }, [ouverte])

  const effacer = async (q: QuestionJournal) => {
    if (!await confirmerTexte('Effacer cette question du journal ?')) return
    try {
      await journalQuestionsApi.effacer(q.id)
      if (ouverte === q.id) setOuverte(null)
      await charger()
    } catch { setErreur('Question non effacée') }
  }
  const effacerTout = async () => {
    const qui = tous ? 'de TOUS les utilisateurs' : 'que vous avez posées'
    if (!await confirmerTexte(`Effacer toutes les questions ${qui} ?\nAction irréversible.`, 'Tout effacer')) return
    try {
      await journalQuestionsApi.effacerTout(tous)
      setOuverte(null)
      await charger()
    } catch { setErreur('Journal non effacé') }
  }
  const changerRetention = async (j: number) => {
    if (j > 0 && (retention === 0 || (retention ?? 0) > j)
        && !await confirmerTexte(`Effacer définitivement les questions de plus de ${j} jours ?\nAction irréversible.`)) return
    const avant = retention
    setRetention(j)
    try {
      await systemApi.updateConfig({ rag_questions_retention_jours: String(j) })
    } catch {
      setRetention(avant); setErreur('Réglage non enregistré')
    }
  }

  return (
    <div className="pt-1 space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <select value={origine} onChange={e => setOrigine(e.target.value as OrigineQuestion | '')}
          aria-label="Origine des questions"
          className="border border-gray-200 rounded px-2 py-1 bg-white text-gray-700">
          <option value="">Chat et mode Question</option>
          <option value="chat">Chat</option>
          <option value="question">Mode Question (GED)</option>
        </select>
        <button type="button" onClick={charger} title="Actualiser" aria-label="Actualiser"
          className="p-1 text-gray-400 hover:text-gray-600">
          <RefreshCw size={13} className={chargement ? 'animate-spin' : ''} />
        </button>
        <span className="text-gray-400">{total} question(s)</span>
        <span className="ml-auto flex items-center gap-2">
          {tous ? (
            <label className="flex items-center gap-1.5 text-gray-500"
              title="Les questions plus anciennes sont effacées automatiquement (passe toutes les 30 min)">
              Conserver
              <select value={retention ?? 180} onChange={e => changerRetention(Number(e.target.value))}
                className="border border-gray-200 rounded px-1.5 py-0.5 bg-white text-gray-700">
                {CONSERVATION.map(o => <option key={o.j} value={o.j}>{o.label}</option>)}
              </select>
            </label>
          ) : retention != null && (
            <span className="text-gray-400">
              {retention > 0 ? `Gardées ${retention} jours, sur ce serveur uniquement` : 'Gardées sur ce serveur uniquement'}
            </span>
          )}
          <button type="button" onClick={effacerTout} disabled={questions.length === 0}
            className="flex items-center gap-1 px-2 py-1 rounded border border-gray-200 text-gray-500 hover:text-red-600 hover:border-red-200 disabled:opacity-40">
            <Trash2 size={12} /> Tout effacer
          </button>
        </span>
      </div>
      {erreur && <p className="text-xs text-red-500">{erreur}</p>}

      {chargement && questions.length === 0 ? (
        <div className="flex justify-center py-4"><Loader2 size={16} className="animate-spin text-gray-400" /></div>
      ) : questions.length === 0 ? (
        <p className="text-xs text-gray-400 py-2">
          Aucune question. Les questions posées au chat (GED en Auto ou Toujours) et au mode Question de la GED apparaîtront ici.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100 max-h-[28rem] overflow-auto">
          {questions.map(q => {
            const st = STATUT[q.statut] ?? STATUT.ok
            const deplie = ouverte === q.id
            return (
              <li key={q.id}>
                <div className="flex items-center gap-2 py-1.5 text-xs">
                  <button type="button" onClick={() => setOuverte(deplie ? null : q.id)} aria-expanded={deplie}
                    className={clsx('flex-1 min-w-0 flex items-center gap-2 text-left hover:bg-gray-50 rounded px-1',
                      deplie && 'bg-violet-50/50')}>
                    {deplie ? <ChevronDown size={13} className="text-gray-400 shrink-0" /> : <ChevronRight size={13} className="text-gray-400 shrink-0" />}
                    {q.origine === 'chat'
                      ? <MessageSquare size={13} className="text-violet-500 shrink-0" aria-label="Chat" />
                      : <Search size={13} className="text-blue-500 shrink-0" aria-label="Mode Question" />}
                    {tous && q.auteur && <span className="text-blue-700 w-24 shrink-0 truncate" title={q.auteur}>{q.auteur}</span>}
                    <span className="flex-1 truncate text-gray-700">{q.question}</span>
                    <span className="text-gray-400 shrink-0">{q.nb_sources} doc.</span>
                    <span className={clsx('shrink-0 w-20 text-right', st.classe)}>{st.label}</span>
                    <span className="text-gray-400 shrink-0 tabular-nums w-12 text-right">{duree(q.duree_ms)}</span>
                    <span className="text-gray-300 shrink-0 w-28 text-right">{quand(q.created_at)}</span>
                  </button>
                  <button type="button" onClick={() => effacer(q)} title="Effacer cette question" aria-label="Effacer cette question"
                    className="p-1 text-gray-300 hover:text-red-500 shrink-0">
                    <Trash2 size={13} />
                  </button>
                </div>
                {deplie && (detail?.id === q.id
                  ? <Detail d={detail} />
                  : <div className="ml-6 mb-2"><Loader2 size={13} className="animate-spin text-gray-400" /></div>)}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/** Fenêtre « Mes questions à l'IA » (chat, mode Question) : les questions de l'utilisateur connecté. */
export function FenetreJournalQuestions({ onFermer }: { onFermer: () => void }) {
  useEffect(() => {
    const echap = (e: KeyboardEvent) => { if (e.key === 'Escape') onFermer() }
    window.addEventListener('keydown', echap)
    return () => window.removeEventListener('keydown', echap)
  }, [onFermer])
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onFermer}>
      <div role="dialog" aria-modal="true" aria-labelledby="titre-journal-questions"
        className="bg-white rounded-xl shadow-xl w-full max-w-4xl max-h-[85vh] overflow-auto p-4"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-2">
          <History size={16} className="text-violet-500" />
          <h2 id="titre-journal-questions" className="text-sm font-semibold text-gray-800">Mes questions à l'IA</h2>
          <button type="button" onClick={onFermer} aria-label="Fermer"
            className="ml-auto p-1 text-gray-400 hover:text-gray-600 rounded-md hover:bg-gray-100">
            <X size={16} />
          </button>
        </div>
        <JournalQuestions />
      </div>
    </div>
  )
}
