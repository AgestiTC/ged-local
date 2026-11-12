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
import { chatApi, ChatRefus, type ChatMessage, type GedMode } from '../api'
import { refusEnvoiIa } from '../utils/gardeEnvoiIa'

interface ChatState {
  messages: ChatMessage[]
  input: string
  model: string          // '' = Auto (modèle « chat » des Paramètres)
  gedMode: GedMode       // 'auto' (défaut) : GED consultée si la question la vise · 'toujours' · 'jamais'
  streaming: boolean
  alerte: string | null  // envoi refusé par la garde de destination IA (message à afficher ; non persisté)
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
  alerte: null,
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
    // Relecture de la destination juste avant l'envoi (jamais sur un état périmé). Pendant ce temps, on
    // se déclare « en cours » pour qu'un second clic ne double pas l'envoi.
    set({ streaming: true, alerte: null })
    const refus = await refusEnvoiIa()
    if (refus) { set({ streaming: false, alerte: refus }); return }   // la saisie est conservée
    const historique: ChatMessage[] = [...messages, { role: 'user', content: texte }]
    set({ messages: [...historique, { role: 'assistant', content: '' }], input: '', streaming: true })
    const ac = new AbortController()
    set({ _abort: ac })
    try {
      const complet = await chatApi.stream(historique, model, gedMode, (chunk) => {
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
      // Le serveur écrit « ⚠️ IA injoignable (…) » DANS le flux quand l'IA locale ne répond pas : champ structuré,
      // posé une seule fois (une erreur GECO, écrite « ⚠️ <message> », ne le déclenche pas).
      if (typeof complet === 'string' && complet.startsWith('⚠️ IA injoignable')) {
        set((s) => {
          const c = [...s.messages]
          c[c.length - 1] = { ...c[c.length - 1], erreurIaLocale: true }
          return { messages: c }
        })
      }
    } catch (e) {
      if (!ac.signal.aborted) {
        // Refus explicite du serveur (modèle non installé / GECO…) : on affiche SON message.
        const refuse = e instanceof ChatRefus
        const texte = refuse ? `⚠️ ${e.message}` : '⚠️ IA injoignable.'
        set((s) => {
          const c = [...s.messages]
          if (!c[c.length - 1].content) {
            c[c.length - 1] = refuse
              ? { role: 'assistant', content: texte }
              : { role: 'assistant', content: texte, erreurIaLocale: true }
          }
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
  // `erreurIaLocale` n'est JAMAIS persisté : la proposition de repli ne réapparaît pas au rechargement.
  partialize: (s) => ({
    messages: s.messages.map(({ erreurIaLocale: _omis, ...m }) => m), model: s.model, gedMode: s.gedMode,
  }),
  version: 1,
  migrate: migrerChat,
}))
