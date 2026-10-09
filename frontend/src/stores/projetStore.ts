/**
 * Projets de la page Créer — brouillon sauvegardé automatiquement, repris plus tard.
 * Plan : docs/plan-projets-creer.md.
 *
 * L'état d'une tuile est DISPERSÉ (magasins, composants). Plutôt que de tout centraliser, chaque
 * morceau s'inscrit avec `useProjetPart(cle, valeur, appliquer)` : sa valeur est collectée à la
 * sauvegarde, et `appliquer` la remet en place quand on rouvre le projet. Un composant monté plus
 * tard (ex. la musique, affichée seulement sur sa tuile) reçoit sa part à son montage.
 */
import { useEffect, useRef } from 'react'
import { create } from 'zustand'
import { projetsApi, type ProjetDetail } from '../api'

const DEBOUNCE_MS = 2000
const VERSION_ETAT = 1

type Part = { valeur: unknown }
const parts = new Map<string, Part>()
let minuterie: ReturnType<typeof setTimeout> | null = null

interface ProjetState {
  projet: { id: string; titre: string; mode: string; updated_at: string | null } | null
  enregistrement: 'repos' | 'en_cours' | 'ok' | 'erreur' | 'conflit'
  enregistreLe: number | null
  /** Incrémenté à chaque ouverture : les parts savent qu'elles doivent se remettre en place. */
  jeton: number
  etatCharge: Record<string, unknown>
  modeCourant: string
  setModeCourant: (mode: string) => void
  commencer: (titre: string) => Promise<void>
  ouvrir: (id: string) => Promise<ProjetDetail>
  fermer: () => void
  renommer: (titre: string) => Promise<void>
  signalerChangement: () => void
  enregistrerMaintenant: () => Promise<void>
  rattacher: (type: 'rapport' | 'job' | 'presentation' | 'morceau', ref: string, libelle?: string) => void
}

function collecter(): Record<string, unknown> {
  const etat: Record<string, unknown> = { version: VERSION_ETAT }
  parts.forEach((p, cle) => { etat[cle] = p.valeur })
  return etat
}

export const useProjetStore = create<ProjetState>((set, get) => ({
  projet: null,
  enregistrement: 'repos',
  enregistreLe: null,
  jeton: 0,
  etatCharge: {},
  modeCourant: 'rapport_libre',
  setModeCourant: (modeCourant) => set({ modeCourant }),

  commencer: async (titre) => {
    const p = await projetsApi.creer({ titre, mode: get().modeCourant, etat: collecter() })
    set({ projet: { id: p.id, titre: p.titre, mode: p.mode, updated_at: p.updated_at },
          enregistrement: 'ok', enregistreLe: Date.now(), etatCharge: {} })
  },

  ouvrir: async (id) => {
    const p = await projetsApi.lire(id)
    set(s => ({ projet: { id: p.id, titre: p.titre, mode: p.mode, updated_at: p.updated_at },
                etatCharge: p.etat || {}, jeton: s.jeton + 1, enregistrement: 'ok', enregistreLe: Date.now() }))
    return p
  },

  fermer: () => {
    if (minuterie) { clearTimeout(minuterie); minuterie = null }
    set({ projet: null, enregistrement: 'repos', etatCharge: {} })
  },

  renommer: async (titre) => {
    const p = get().projet
    if (!p) return
    const r = await projetsApi.sauvegarder(p.id, { titre })
    set({ projet: { ...p, titre: r.titre, updated_at: r.updated_at } })
  },

  signalerChangement: () => {
    if (!get().projet) return
    if (minuterie) clearTimeout(minuterie)
    minuterie = setTimeout(() => { void get().enregistrerMaintenant() }, DEBOUNCE_MS)
  },

  enregistrerMaintenant: async () => {
    const p = get().projet
    if (!p) return
    set({ enregistrement: 'en_cours' })
    try {
      const r = await projetsApi.sauvegarder(p.id, { etat: collecter(), mode: get().modeCourant, version: p.updated_at })
      set({ projet: { ...p, updated_at: r.updated_at, mode: r.mode }, enregistrement: 'ok', enregistreLe: Date.now() })
    } catch (e) {
      const statut = (e as { response?: { status?: number } })?.response?.status
      set({ enregistrement: statut === 409 ? 'conflit' : 'erreur' })
    }
  },

  rattacher: (type, ref, libelle) => {
    const p = get().projet
    if (p) projetsApi.rattacher(p.id, { type, ref, libelle }).catch(() => { /* non bloquant */ })
  },
}))

/**
 * Inscrit un morceau de l'état d'une tuile dans le projet ouvert. `valeur` doit être sérialisable
 * en JSON ; `appliquer` la remet en place à l'ouverture d'un projet.
 */
export function useProjetPart<T>(cle: string, valeur: T, appliquer: (v: T) => void) {
  const jeton = useProjetStore(s => s.jeton)
  const applique = useRef(0)
  const appliquerRef = useRef(appliquer)
  appliquerRef.current = appliquer

  // Remise en place : à l'ouverture d'un projet, ou au montage si le projet était déjà ouvert.
  useEffect(() => {
    if (jeton === 0 || applique.current === jeton) return
    applique.current = jeton
    const charge = useProjetStore.getState().etatCharge
    if (cle in charge) appliquerRef.current(charge[cle] as T)
  }, [jeton, cle])

  // Collecte + sauvegarde automatique à chaque changement.
  const serial = JSON.stringify(valeur)
  useEffect(() => {
    parts.set(cle, { valeur: JSON.parse(serial) })
    useProjetStore.getState().signalerChangement()
  }, [cle, serial])
}
