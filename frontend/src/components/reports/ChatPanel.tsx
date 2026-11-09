/**
 * ChatPanel — Dialogue LIBRE avec l'IA (dans « Créer »)
 * =====================================================
 * Chat direct avec le modèle Ollama, **sans lien avec les documents indexés** par défaut (aide à la
 * rédaction, questions, brouillons). Sélecteur **GED** à 3 états : « Auto » (défaut : l'IA ne
 * consulte tes documents que si la question les concerne), « Toujours », « Jamais ».
 * Choix du modèle — « Auto » = modèle « Dialogue avec l'IA » défini dans les Paramètres.
 *
 * L'état vit dans `useChatStore` (Zustand) → la conversation ET le streaming **survivent** au
 * changement de menu / d'onglet du navigateur (le composant peut se démonter sans rien perdre).
 */
import { useEffect, useRef } from 'react'
import { Send, Square, Trash2, Bot, User, Cpu, MessageSquare, Database, ShieldCheck } from 'lucide-react'
import { clsx } from 'clsx'
import type { GedMode } from '../../api'
import { useModeles } from '../../hooks/useModeles'
import { useChatStore } from '../../stores/chatStore'
import SourcesGed from './SourcesGed'

const MODES_GED: { id: GedMode; label: string; aide: string }[] = [
  { id: 'auto', label: 'Auto', aide: "L'IA consulte vos documents seulement si la question les concerne" },
  { id: 'toujours', label: 'Toujours', aide: "L'IA cherche systématiquement dans vos documents" },
  { id: 'jamais', label: 'Jamais', aide: "Aucune consultation de vos documents" },
]
const SOUS_TITRE_GED: Record<GedMode, string> = {
  auto: "· consulte vos documents si la question les concerne",
  toujours: "· s'appuie sur vos documents (GED)",
  jamais: '· sans lien avec vos documents',
}

const SUGGESTIONS = [
  'Rédige un mail poli pour reporter un rendez-vous à la semaine prochaine.',
  'Corrige et améliore ce texte : ',
  'Résume ce texte en 3 points : ',
  'Écris un message de relance de facture, ton courtois mais ferme.',
]

export default function ChatPanel() {
  const { modeles, defaut } = useModeles()
  const { messages, input, model, gedMode, streaming,
    setInput, setModel, setGedMode, envoyer, arreter, effacer } = useChatStore()
  const scrollRef = useRef<HTMLDivElement>(null)

  // Défile en bas à chaque nouveau contenu (y compris au retour sur l'onglet).
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages])

  return (
    <div className="flex flex-col h-full min-h-[60vh] bg-white border border-gray-200 rounded-xl overflow-hidden">
      {/* En-tête : GED + modèle + effacer */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100 bg-gray-50/60">
        <MessageSquare size={15} className="text-violet-500" />
        <span className="text-sm font-medium text-gray-700">Assistant IA — dialogue libre</span>
        {/* Badge de confiance : l'IA est locale — capital car Matothèque traite des documents personnels. */}
        <span title="L'IA tourne sur TON serveur (Ollama), en local. Tes documents personnels et tes messages ne quittent jamais Matothèque — aucune donnée n'est envoyée à un service externe."
          className="flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 whitespace-nowrap cursor-help">
          <ShieldCheck size={11} /> 100% local
        </span>
        <span className="text-xs text-gray-400 hidden sm:inline">
          {SOUS_TITRE_GED[gedMode]}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {/* Sélecteur GED à 3 états : Auto (défaut) · Toujours · Jamais. */}
          <div role="radiogroup" aria-label="Usage de la GED"
            className="flex items-center gap-1 text-xs text-gray-500">
            <Database size={12} />
            <span className="font-medium">GED</span>
            <div className="flex rounded-full border border-gray-200 overflow-hidden bg-white">
              {MODES_GED.map((m, idx) => (
                <button key={m.id} type="button" role="radio" aria-checked={gedMode === m.id}
                  tabIndex={gedMode === m.id ? 0 : -1}
                  onClick={() => setGedMode(m.id)} title={m.aide}
                  onKeyDown={e => {
                    // Radiogroup ARIA : les flèches déplacent le focus ET sélectionnent.
                    const pas = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1
                      : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
                    if (!pas) return
                    e.preventDefault()
                    const suivant = MODES_GED[(idx + pas + MODES_GED.length) % MODES_GED.length]
                    setGedMode(suivant.id)
                    const boutons = e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="radio"]')
                    boutons?.[MODES_GED.indexOf(suivant)]?.focus()
                  }}
                  className={clsx('px-2 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-violet-400',
                    gedMode === m.id
                      ? (m.id === 'jamais' ? 'bg-gray-200 text-gray-700' : 'bg-emerald-50 text-emerald-700')
                      : 'text-gray-500 hover:bg-gray-50')}>
                  {m.label}
                </button>
              ))}
            </div>
          </div>
          <label className="flex items-center gap-1 text-xs text-gray-500">
            <Cpu size={12} />
            <select value={model} onChange={e => setModel(e.target.value)}
              className="text-xs border border-gray-200 rounded-md px-1.5 py-1 bg-white max-w-[160px]">
              <option value="">Auto{defaut ? ` · ${defaut.split(':')[0]}` : ''}</option>
              {modeles.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
            </select>
          </label>
          <button type="button" onClick={effacer} disabled={streaming || messages.length === 0}
            title="Effacer la conversation"
            className="p-1.5 text-gray-400 hover:text-red-500 disabled:opacity-40 rounded-md hover:bg-gray-100">
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      {/* Aide au choix du modèle */}
      <div className="px-3 py-1.5 border-b border-gray-100 bg-white text-[11px] text-gray-400">
        💡 <strong className="text-gray-500">llama3.1</strong> au quotidien (rapide, marge VRAM en mode GED) ·
        <strong className="text-gray-500"> ministral-3</strong> pour un courrier soigné.
      </div>

      {/* Fil de discussion */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center gap-3 text-gray-400">
            <Bot size={40} strokeWidth={1} className="text-violet-300" />
            <p className="text-sm text-gray-500">Pose une question ou demande un coup de main à la rédaction.</p>
            <p className="flex items-center gap-1.5 text-xs text-emerald-600 bg-emerald-50 border border-emerald-100 rounded-full px-3 py-1">
              <ShieldCheck size={13} /> 100% local — tes documents personnels ne quittent jamais Matothèque.
            </p>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg">
              {SUGGESTIONS.map(s => (
                <button key={s} type="button" onClick={() => setInput(s)}
                  className="text-xs px-2.5 py-1.5 rounded-full border border-gray-200 text-gray-600 hover:border-violet-300 hover:bg-violet-50/50 text-left">
                  {s.length > 42 ? s.slice(0, 42) + '…' : s}
                </button>
              ))}
            </div>
          </div>
        ) : messages.map((m, i) => (
          <div key={i} className={clsx('flex gap-2', m.role === 'user' ? 'justify-end' : 'justify-start')}>
            {m.role === 'assistant' && <Bot size={18} className="text-violet-500 mt-1 shrink-0" />}
            <div className="max-w-[80%] min-w-0">
              <div className={clsx('rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap break-words',
                m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-800')}>
                {m.content || <span className="text-gray-400">…</span>}
              </div>
              {/* Bandeau discret : documents de la GED sur lesquels la réponse s'appuie. */}
              {m.role === 'assistant' && m.gedSources && m.gedSources.length > 0 && (
                <SourcesGed sources={m.gedSources} />
              )}
            </div>
            {m.role === 'user' && <User size={18} className="text-blue-500 mt-1 shrink-0" />}
          </div>
        ))}
      </div>

      {/* Saisie */}
      <div className="border-t border-gray-100 p-2.5">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); envoyer() } }}
            rows={2}
            placeholder="Écris ton message… (Entrée pour envoyer, Maj+Entrée = nouvelle ligne)"
            className="flex-1 resize-none text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-300"
          />
          {streaming ? (
            <button type="button" onClick={arreter}
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
    </div>
  )
}
