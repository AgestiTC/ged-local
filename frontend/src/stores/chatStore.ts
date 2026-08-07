/**
 * Store Chat — Zustand
 * ====================
 * État du dialogue libre avec l'IA (page Créer). Sorti du composant EXPRÈS : le store est un
 * singleton de module → la conversation ET le streaming en cours **survivent** au changement de
 * menu dans Matothèque (démontage du composant) et au passage sur un autre onglet du navigateur.
 * Le `fetch` de streaming tourne dans l'action `envoyer`, indépendamment du cycle de vie du composant.
 */
import { create } from 'zustand'
import { chatApi, type ChatMessage } from '../api'

interface ChatState {
  messages: ChatMessage[]
  input: string
  model: string          // '' = Auto (modèle « chat » des Paramètres)
  useGed: boolean        // l'IA pioche dans les documents indexés (RAG)
  streaming: boolean
  _abort: AbortController | null
  setInput: (v: string) => void
  setModel: (v: string) => void
  setUseGed: (v: boolean) => void
  envoyer: () => Promise<void>
  arreter: () => void
  effacer: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  input: '',
  model: '',
  useGed: false,
  streaming: false,
  _abort: null,

  setInput: (v) => set({ input: v }),
  setModel: (v) => set({ model: v }),
  setUseGed: (v) => set({ useGed: v }),
  arreter: () => get()._abort?.abort(),
  effacer: () => { if (!get().streaming) set({ messages: [], input: '' }) },

  envoyer: async () => {
    const { input, messages, model, useGed, streaming } = get()
    const texte = input.trim()
    if (!texte || streaming) return
    const historique: ChatMessage[] = [...messages, { role: 'user', content: texte }]
    set({ messages: [...historique, { role: 'assistant', content: '' }], input: '', streaming: true })
    const ac = new AbortController()
    set({ _abort: ac })
    try {
      await chatApi.stream(historique, model, useGed, (chunk) => {
        set((s) => {
          const c = [...s.messages]
          c[c.length - 1] = { role: 'assistant', content: c[c.length - 1].content + chunk }
          return { messages: c }
        })
      }, ac.signal)
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
}))
