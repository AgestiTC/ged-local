/**
 * Store Chat — Zustand
 * ====================
 * État du dialogue libre avec l'IA (page Créer). Sorti du composant EXPRÈS : le store est un
 * singleton de module → la conversation ET le streaming en cours **survivent** au changement de
 * menu dans Matothèque (démontage du composant) et au passage sur un autre onglet du navigateur.
 * Le `fetch` de streaming tourne dans l'action `envoyer`, indépendamment du cycle de vie du composant.
 *
 * `persist` (localStorage) : la conversation, le modèle et le mode GED survivent AUSSI à un
 * rechargement complet de la page (F5). Le streaming en cours, lui, n'est pas reprenable après un
 * F5 (un `fetch` ne se rejoue pas) — on ne persiste donc que les données, pas l'état « en cours ».
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { chatApi, type ChatMessage, type GedMode } from '../api'

interface ChatState {
  messages: ChatMessage[]
  input: string
  model: string          // '' = Auto (modèle « chat » des Paramètres)
  gedMode: GedMode       // 'auto' (défaut) : GED consultée si la question la vise · 'toujours' · 'jamais'
  streaming: boolean
  _abort: AbortController | null
  setInput: (v: string) => void
  setModel: (v: string) => void
  setGedMode: (v: GedMode) => void
  envoyer: () => Promise<void>
  arreter: () => void
  effacer: () => void
}

/**
 * Migration du localStorage. v0 persistait `useGed: boolean` (défaut false, jamais un choix
 * conscient pour la plupart des utilisateurs) : true → 'toujours' (choix explicite conservé),
 * false → 'auto' (le nouveau défaut — sinon la correction ne profiterait à personne).
 */
export function migrerChat(persisted: unknown, version: number): Partial<ChatState> {
  const p = (persisted ?? {}) as Record<string, unknown>
  if (version < 1) {
    const { useGed, ...reste } = p
    return { ...reste, gedMode: useGed === true ? 'toujours' : 'auto' } as Partial<ChatState>
  }
  // Valeur du localStorage non fiable : tout ce qui n'est pas un mode connu retombe sur 'auto'.
  const modes: GedMode[] = ['auto', 'toujours', 'jamais']
  const gedMode = modes.includes(p.gedMode as GedMode) ? (p.gedMode as GedMode) : 'auto'
  return { ...p, gedMode } as Partial<ChatState>
}

export const useChatStore = create<ChatState>()(persist((set, get) => ({
  messages: [],
  input: '',
  model: '',
  gedMode: 'auto',
  streaming: false,
  _abort: null,

  setInput: (v) => set({ input: v }),
  setModel: (v) => set({ model: v }),
  setGedMode: (v) => set({ gedMode: v }),
  arreter: () => get()._abort?.abort(),
  effacer: () => { if (!get().streaming) set({ messages: [], input: '' }) },

  envoyer: async () => {
    const { input, messages, model, gedMode, streaming } = get()
    const texte = input.trim()
    if (!texte || streaming) return
    const historique: ChatMessage[] = [...messages, { role: 'user', content: texte }]
    set({ messages: [...historique, { role: 'assistant', content: '' }], input: '', streaming: true })
    const ac = new AbortController()
    set({ _abort: ac })
    try {
      await chatApi.stream(historique, model, gedMode, (chunk) => {
        set((s) => {
          const c = [...s.messages]
          const dernier = c[c.length - 1]
          c[c.length - 1] = { ...dernier, content: dernier.content + chunk }
          return { messages: c }
        })
      }, ac.signal, (meta) => {
        // Sources GED de CETTE réponse (en-têtes), rattachées au message assistant en cours.
        if (!meta.gedUtilise) return
        set((s) => {
          const c = [...s.messages]
          c[c.length - 1] = { ...c[c.length - 1], gedSources: meta.sources }
          return { messages: c }
        })
      })
    } catch {
      if (!ac.signal.aborted) {
        set((s) => {
          const c = [...s.messages]
          if (!c[c.length - 1].content) c[c.length - 1] = { role: 'assistant', content: '⚠️ IA injoignable.' }
          return { messages: c }
        })
      }
    } finally {
      set({ streaming: false, _abort: null })
    }
  },
}), {
  name: 'matotheque-chat',
  // On ne persiste QUE les données utiles (pas `streaming`/`_abort`, ni la saisie en cours) →
  // au rechargement, la conversation revient mais aucun « streaming » fantôme n'est restauré.
  partialize: (s) => ({ messages: s.messages, model: s.model, gedMode: s.gedMode }),
  version: 1,
  migrate: migrerChat,
}))
