/**
 * Page « Assistant IA internet » — le pont entre le local et une IA web
 * ====================================================================
 * L'app reste 100 % LOCALE : cette page n'appelle AUCUN service externe. L'IA locale
 * (Ollama) t'aide seulement à **fabriquer un excellent prompt** de recherche documentaire,
 * que TU copies dans une vraie IA connectée au web (Claude, ChatGPT, Perplexity…). Tu
 * reviens ensuite **coller la réponse** ici : elle est analysée en local (Import IA) et
 * ajoutée aux ressources d'un dossier. Le circuit boucle sans que l'app ne sorte du réseau.
 *
 * Même esprit que « Créer › Discuter avec l'IA » (chat local, streaming), mais orienté veille.
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft, Bot, Check, Copy, Globe, Send, ShieldCheck, Sparkles, Square, User,
} from 'lucide-react'
import { clsx } from 'clsx'
import { chatApi, dossiersApi, type ChatMessage, type DossierResume, type RessourceInput } from '../api'
import { useToast } from '../components/common/Toast'
import { copierTexte } from '../utils/clipboard'

// Prime le modèle local : il ne CHERCHE pas (pas d'accès web), il RÉDIGE le prompt à copier.
const SYSTEME: ChatMessage = {
  role: 'system',
  content:
    "Tu es un assistant qui aide à FORMULER un excellent prompt de recherche documentaire, " +
    "destiné à être COPIÉ dans une IA connectée au web (Claude, ChatGPT, Perplexity). Tu n'as PAS " +
    "accès à Internet et tu ne fais PAS la recherche toi-même : tu produis LE PROMPT à copier. Le " +
    "prompt doit demander une liste de ressources (podcasts, vidéos/chaînes, documentaires, films, " +
    "livres, BD, articles, études, rapports, associations) avec, pour CHACUNE : titre, auteur/éditeur, " +
    "type, URL si elle est connue (sans jamais inventer d'URL), et une phrase de description. Il doit " +
    "exiger un rendu en TABLEAU MARKDOWN (colonnes : Titre | Auteur | Type | URL | Description) facile " +
    "à copier. Réponds en français, brièvement, puis termine TOUJOURS par le prompt final seul, dans un " +
    "bloc de code.",
}

const EXEMPLES = [
  'Trouve-moi des ressources fiables sur le sommeil du nourrisson (0-1 an).',
  'Podcasts et livres sur la diversification alimentaire menée par l’enfant (DME).',
  'Documentaires et associations sur la parentalité positive (2-5 ans).',
]

export default function IAInternetPage() {
  const toast = useToast()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Retour de la réponse web → Import IA → dossier.
  const [dossiers, setDossiers] = useState<DossierResume[]>([])
  const [cible, setCible] = useState('')
  const [reponse, setReponse] = useState('')
  const [apercu, setApercu] = useState<RessourceInput[] | null>(null)
  const [sel, setSel] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState(false)

  useEffect(() => { dossiersApi.list().then(setDossiers).catch(() => {}) }, [])
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight }) }, [messages])

  const envoyer = async () => {
    const texte = input.trim()
    if (!texte || streaming) return
    const historique: ChatMessage[] = [...messages, { role: 'user', content: texte }]
    setMessages([...historique, { role: 'assistant', content: '' }])
    setInput(''); setStreaming(true)
    const ac = new AbortController(); abortRef.current = ac
    try {
      await chatApi.stream([SYSTEME, ...historique], '', false, (chunk) => {
        setMessages(m => {
          const c = [...m]; c[c.length - 1] = { role: 'assistant', content: c[c.length - 1].content + chunk }; return c
        })
      }, ac.signal)
    } catch {
      if (!ac.signal.aborted) setMessages(m => {
        const c = [...m]; if (!c[c.length - 1].content) c[c.length - 1] = { role: 'assistant', content: '⚠️ IA locale injoignable.' }; return c
      })
    } finally { setStreaming(false); abortRef.current = null }
  }

  const copier = (t: string) => copierTexte(t).then(() => toast.success('Prompt copié — colle-le dans ton IA web.'))

  // ── Retour de la réponse ────────────────────────────────────────────────────
  const analyser = async () => {
    if (!reponse.trim()) return
    setBusy(true)
    try {
      const r = await dossiersApi.parseImport(reponse)
      setApercu(r.ressources); setSel(new Set(r.ressources.map((_, i) => i)))
      if (r.ressources.length === 0) toast.error('Aucune ressource détectée dans la réponse collée.')
    } catch { toast.error('Analyse impossible (IA locale injoignable ?).') } finally { setBusy(false) }
  }

  const ajouter = async () => {
    if (!apercu || !cible) { toast.error('Choisis un dossier cible.'); return }
    const choisies = apercu.filter((_, i) => sel.has(i))
    if (choisies.length === 0) { toast.error('Coche au moins une ressource.'); return }
    setBusy(true)
    try {
      const r = await dossiersApi.importRessources(cible, choisies)
      toast.success(`${r.ajoutees} ressource(s) ajoutée(s)${r.ignorees ? ` · ${r.ignorees} déjà présente(s)` : ''}`)
      setApercu(null); setReponse(''); setSel(new Set())
    } catch { toast.error('Ajout impossible.') } finally { setBusy(false) }
  }

  return (
    <div className="max-w-4xl mx-auto p-4 space-y-4">
      <Link to="/dossiers" className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700">
        <ArrowLeft size={15} /> Dossiers
      </Link>

      <header>
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <Globe size={18} className="text-blue-600" /> Assistant IA internet
        </h1>
        <p className="text-sm text-gray-500 mt-1 max-w-2xl">
          L'IA <strong>locale</strong> te fabrique un prompt à copier dans une IA web (Claude, ChatGPT,
          Perplexity). Tu ramènes ensuite la réponse ici — elle est ajoutée à un dossier. L'application,
          elle, ne sort <strong>jamais</strong> sur Internet.
        </p>
        <span className="mt-2 inline-flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-3 py-1">
          <ShieldCheck size={13} /> 100 % local — cette page n'appelle aucun service externe.
        </span>
      </header>

      {/* Étape 1 — Fabriquer le prompt (chat local) */}
      <section className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100 bg-gray-50/60">
          <Sparkles size={15} className="text-violet-500" />
          <span className="text-sm font-medium text-gray-700">1. Décris ton besoin → l'IA prépare le prompt</span>
        </div>

        <div ref={scrollRef} className="max-h-[46vh] overflow-y-auto p-3 space-y-3">
          {messages.length === 0 ? (
            <div className="py-6 flex flex-col items-center text-center gap-3 text-gray-400">
              <Bot size={36} strokeWidth={1} className="text-violet-300" />
              <p className="text-sm text-gray-500">Dis ce que tu cherches — l'IA te rend un prompt prêt à copier.</p>
              <div className="flex flex-wrap gap-2 justify-center max-w-lg">
                {EXEMPLES.map(s => (
                  <button key={s} type="button" onClick={() => setInput(s)}
                    className="text-xs px-2.5 py-1.5 rounded-full border border-gray-200 text-gray-600 hover:border-violet-300 hover:bg-violet-50/50 text-left">
                    {s.length > 46 ? s.slice(0, 46) + '…' : s}
                  </button>
                ))}
              </div>
            </div>
          ) : messages.map((m, i) => (
            <div key={i} className={clsx('flex gap-2', m.role === 'user' ? 'justify-end' : 'justify-start')}>
              {m.role === 'assistant' && <Bot size={18} className="text-violet-500 mt-1 shrink-0" />}
              <div className={clsx('max-w-[85%] rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap break-words',
                m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-800')}>
                {m.content || <span className="text-gray-400">…</span>}
                {m.role === 'assistant' && m.content && !streaming && (
                  <button type="button" onClick={() => copier(m.content)}
                    className="mt-2 flex items-center gap-1 text-xs text-violet-600 hover:text-violet-800">
                    <Copy size={12} /> Copier ce prompt
                  </button>
                )}
              </div>
              {m.role === 'user' && <User size={18} className="text-blue-500 mt-1 shrink-0" />}
            </div>
          ))}
        </div>

        <div className="border-t border-gray-100 p-2.5">
          <div className="flex items-end gap-2">
            <textarea value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); envoyer() } }}
              rows={2} placeholder="Ex. : ressources fiables sur le sommeil du nourrisson…"
              className="flex-1 resize-none text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-300" />
            {streaming ? (
              <button type="button" onClick={() => abortRef.current?.abort()}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-lg bg-gray-700 text-white hover:bg-gray-800">
                <Square size={14} /> Stop
              </button>
            ) : (
              <button type="button" onClick={envoyer} disabled={!input.trim()}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-40">
                <Send size={14} /> Envoyer
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Étape 2 — Coller la réponse de l'IA web → dossier */}
      <section className="bg-white border border-gray-200 rounded-xl p-3 space-y-3">
        <div className="flex items-center gap-2">
          <Globe size={15} className="text-blue-500" />
          <span className="text-sm font-medium text-gray-700">2. Colle la réponse de l'IA web → ajoute à un dossier</span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-gray-500">Dossier cible :</label>
          <select value={cible} onChange={e => setCible(e.target.value)}
            className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white">
            <option value="">— choisir —</option>
            {dossiers.map(d => <option key={d.id} value={d.slug}>{d.titre}</option>)}
          </select>
        </div>

        <textarea value={reponse} onChange={e => setReponse(e.target.value)}
          rows={5} placeholder="Colle ici la réponse (tableau markdown) renvoyée par l'IA web…"
          className="w-full resize-y text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300" />

        <div className="flex items-center gap-2">
          <button type="button" onClick={analyser} disabled={busy || !reponse.trim()}
            className="inline-flex items-center gap-1.5 text-sm font-medium bg-blue-600 text-white rounded-md px-3 py-1.5 hover:bg-blue-700 disabled:opacity-50">
            <Sparkles size={14} /> {busy ? 'Analyse…' : 'Analyser (IA locale)'}
          </button>
          <span className="text-[11px] text-gray-400">L'IA locale ne fait qu'extraire ce que tu colles (aucune URL inventée).</span>
        </div>

        {/* Aperçu à valider */}
        {apercu && (
          <div className="border border-gray-100 rounded-lg divide-y divide-gray-100">
            {apercu.length === 0 && <p className="text-xs text-gray-400 p-3">Aucune ressource détectée.</p>}
            {apercu.map((r, i) => (
              <label key={i} className="flex items-start gap-2 p-2.5 text-sm cursor-pointer hover:bg-gray-50">
                <input type="checkbox" checked={sel.has(i)} className="mt-1"
                  onChange={() => setSel(s => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })} />
                <span className="min-w-0">
                  <span className="font-medium text-gray-800">{r.titre}</span>
                  {r.auteur && <span className="text-gray-400"> — {r.auteur}</span>}
                  {r.type && <span className="ml-1.5 text-[10px] uppercase tracking-wide text-gray-400 border border-gray-200 rounded px-1 py-0.5">{r.type}</span>}
                  {r.note && <span className="block text-xs text-gray-500 mt-0.5">{r.note}</span>}
                  {r.url && <span className="block text-xs text-blue-500 truncate">{r.url}</span>}
                </span>
              </label>
            ))}
            {apercu.length > 0 && (
              <div className="flex items-center gap-2 p-2.5">
                <button type="button" onClick={ajouter} disabled={busy}
                  className="inline-flex items-center gap-1.5 text-sm font-medium bg-emerald-600 text-white rounded-md px-3 py-1.5 hover:bg-emerald-700 disabled:opacity-50">
                  <Check size={14} /> Ajouter au dossier ({sel.size})
                </button>
                <button type="button" onClick={() => setApercu(null)} className="text-xs text-gray-400 hover:text-gray-600">Annuler</button>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
