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

export interface OptionsConfirmation {
  titre: string
  contenu?: ReactNode
  confirmer?: string
  annuler?: string
}

type Demande = OptionsConfirmation & { repondre: (ok: boolean) => void }

const ConfirmationContext = createContext<(o: OptionsConfirmation) => Promise<boolean>>(
  async () => false)

export function ConfirmationProvider({ children }: { children: ReactNode }) {
  const [demande, setDemande] = useState<Demande | null>(null)

  const demander = useCallback((o: OptionsConfirmation) => new Promise<boolean>(resolve => {
    setDemande({ ...o, repondre: ok => { setDemande(null); resolve(ok) } })
  }), [])

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
    ok.current?.focus()
    const surTouche = (e: KeyboardEvent) => { if (e.key === 'Escape') demande.repondre(false) }
    window.addEventListener('keydown', surTouche)
    return () => window.removeEventListener('keydown', surTouche)
  }, [demande])

  return (
    <div className="fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={() => demande.repondre(false)}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirmation-titre"
        className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col text-sm"
        onClick={e => e.stopPropagation()}>
        <h2 id="confirmation-titre" className="px-5 pt-4 pb-2 text-base font-semibold text-gray-800">{demande.titre}</h2>
        {demande.contenu && <div className="px-5 pb-2 overflow-y-auto text-gray-700">{demande.contenu}</div>}
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-gray-100 mt-2">
          <button type="button" onClick={() => demande.repondre(false)}
            className="px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">
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
