/**
 * Fenêtre de confirmation de l'application — à la place de `window.confirm` (04/11/2026).
 * La boîte du navigateur affichait « ged.tclement.fr indique » au-dessus d'un texte brut : on
 * voulait la fenêtre de Matothèque, fond flouté, avec sa mise en forme.
 *
 * Usage : const confirmer = useConfirmation()
 *         if (!(await confirmer({ titre: 'Créer les candidats ?', contenu: <…/> }))) return
 * Échap ou clic sur le fond = Annuler ; Entrée = Confirmer (bouton focalisé à l'ouverture).
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { X } from 'lucide-react'

export interface OptionsConfirmation {
  titre: string
  contenu?: ReactNode
  confirmer?: string
  annuler?: string
  /** Laisser le focus au contenu (champ de saisie) plutôt qu'au bouton Confirmer. */
  focusContenu?: boolean
}

type Demande = OptionsConfirmation & { repondre: (ok: boolean) => void }

const ConfirmationContext = createContext<(o: OptionsConfirmation) => Promise<boolean>>(
  async () => false)

// Fenêtre accessible hors composant React, pour remplacer un `confirm(texte)` sans changer l'écran.
let demanderGlobal: ((o: OptionsConfirmation) => Promise<boolean>) | null = null

/**
 * Remplaçant direct de `confirm(message)` : 1re ligne = titre, le reste = texte (sauts de ligne gardés).
 * Sans fournisseur monté (tests unitaires d'un composant seul), retombe sur `window.confirm`.
 */
export function confirmerTexte(message: string, confirmer?: string): Promise<boolean> {
  if (!demanderGlobal) return Promise.resolve(window.confirm(message))
  const [titre, ...reste] = message.split('\n')
  const texte = reste.join('\n').trim()
  return demanderGlobal({
    titre, confirmer,
    contenu: texte ? <p className="whitespace-pre-line">{texte}</p> : undefined,
  })
}

/** Remplaçant de `prompt(question, défaut)` : renvoie le texte saisi, ou null si annulé. */
export async function saisirTexte(question: string, defaut = ''): Promise<string | null> {
  if (!demanderGlobal) return window.prompt(question, defaut)
  let valeur = defaut
  const ok = await demanderGlobal({
    titre: question, confirmer: 'Valider', focusContenu: true,
    contenu: <input autoFocus defaultValue={defaut} onChange={e => { valeur = e.target.value }}
      className="w-full border border-gray-200 rounded-md px-2 py-1.5" />,
  })
  return ok ? valeur : null
}

export function ConfirmationProvider({ children }: { children: ReactNode }) {
  const [demande, setDemande] = useState<Demande | null>(null)

  const demander = useCallback((o: OptionsConfirmation) => new Promise<boolean>(resolve => {
    setDemande({ ...o, repondre: ok => { setDemande(null); resolve(ok) } })
  }), [])

  useEffect(() => {
    demanderGlobal = demander
    return () => { if (demanderGlobal === demander) demanderGlobal = null }
  }, [demander])

  return (
    <ConfirmationContext.Provider value={demander}>
      {children}
      {demande && <Fenetre demande={demande} />}
    </ConfirmationContext.Provider>
  )
}

export const useConfirmation = () => useContext(ConfirmationContext)

function Fenetre({ demande }: { demande: Demande }) {
  const ok = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!demande.focusContenu) ok.current?.focus()
    const surTouche = (e: KeyboardEvent) => {
      if (e.key === 'Escape') demande.repondre(false)
      // Entrée dans le champ de saisie = Valider (comme la boîte du navigateur)
      else if (e.key === 'Enter' && demande.focusContenu && e.target instanceof HTMLInputElement) demande.repondre(true)
    }
    window.addEventListener('keydown', surTouche)
    return () => window.removeEventListener('keydown', surTouche)
  }, [demande])

  return (
    <div className="fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={() => demande.repondre(false)}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirmation-titre"
        className="bg-white rounded-2xl shadow-2xl border border-gray-200 w-full max-w-lg max-h-[85vh] flex flex-col text-sm"
        onClick={e => e.stopPropagation()}>
        {/* En-tête façon fiche NetSight : titre en gras, croix ronde à droite, filet dessous */}
        <div className="flex items-start justify-between gap-4 px-6 py-4 border-b border-gray-200">
          <h2 id="confirmation-titre" className="text-lg font-bold text-gray-900 leading-snug">{demande.titre}</h2>
          <button type="button" aria-label="Fermer" onClick={() => demande.repondre(false)}
            className="shrink-0 w-8 h-8 rounded-full border border-blue-400 text-blue-500 hover:bg-blue-500/10 flex items-center justify-center">
            <X size={16} />
          </button>
        </div>
        {demande.contenu && <div className="px-6 py-4 overflow-y-auto text-gray-700">{demande.contenu}</div>}
        <div className="flex justify-end gap-2 px-6 py-3 border-t border-gray-200">
          <button type="button" onClick={() => demande.repondre(false)}
            className="px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-500/10">
            {demande.annuler ?? 'Annuler'}
          </button>
          <button type="button" ref={ok} onClick={() => demande.repondre(true)}
            className="px-4 py-1.5 rounded-lg bg-blue-600 text-white font-semibold hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-300">
            {demande.confirmer ?? 'Confirmer'}
          </button>
        </div>
      </div>
    </div>
  )
}
