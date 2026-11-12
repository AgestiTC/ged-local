/**
 * ConfirmationSortieInternet — fenêtre de confirmation avant toute sortie sur Internet.
 * Extraite telle quelle du `netConfirm` de la page Paramètres (même rendu) pour que le bouton
 * « IA LOCAL / IA GECO » de l'en-tête n'ait pas SA propre fenêtre : une seule fenêtre de sortie
 * internet dans le projet.
 *
 * Accessibilité : focus initial sur « Annuler » (jamais sur l'action qui sort), Échap = annuler, piège de
 * focus (Tab reste dans la fenêtre), `aria-labelledby` sur le titre, clics ignorés les 300 premières ms
 * (un double-clic qui a ouvert la fenêtre ne doit pas la confirmer).
 *
 * Pied par défaut : exact selon la destination de l'IA — la phrase « 100% local » n'est dite que quand la
 * destination est LUE et locale ; en mode GECO, « cette action n'envoie aucun document » reste vraie, et
 * l'IA GECO active est rappelée. `pied` le remplace.
 */
import { useEffect, useRef, type ReactNode } from 'react'
import { useIaDestinationStore } from '../../stores/iaDestinationStore'
import type { EtatIa } from '../../utils/iaDestination'

export const CLIC_IGNORE_MS = 300

/** Un clic est-il pris en compte ? Pas dans les `CLIC_IGNORE_MS` qui suivent l'ouverture. */
export function clicAccepte(ouvertA: number, maintenant: number): boolean {
  return maintenant - ouvertA >= CLIC_IGNORE_MS
}

/** Pied par défaut selon la destination de l'IA. */
export function PiedParDefaut({ destination }: { destination: EtatIa }) {
  if (destination === 'geco') {
    return <p>Cette action n'envoie aucun document. L'IA GECO est par ailleurs activée.</p>
  }
  if (destination === 'local') {
    return (
      <p>
        Matothèque reste <strong>100% local</strong> : c'est le seul moment où l'on sort sur
        Internet, et uniquement parce que tu l'as demandé. <strong>Aucun document</strong> n'est envoyé.
      </p>
    )
  }
  return <p>Cette action n'envoie aucun document.</p>
}

interface Props {
  titre: string
  message: ReactNode
  pied?: ReactNode
  /** Une action est en cours : « Continuer » est occupé et inactif. */
  occupe?: boolean
  onAnnuler: () => void
  onConfirmer: () => void
}

const FOCALISABLES = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function ConfirmationSortieInternet({ titre, message, pied, occupe, onAnnuler, onConfirmer }: Props) {
  const destination = useIaDestinationStore(s => s.destination)
  const ouvertA = useRef(Date.now())
  const fenetre = useRef<HTMLDivElement>(null)
  const annuler = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    ouvertA.current = Date.now()
    const precedent = document.activeElement as HTMLElement | null   // rendu au déclencheur à la fermeture
    annuler.current?.focus()                      // focus initial : « Annuler »
    const surTouche = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onAnnuler(); return }
      if (e.key !== 'Tab' || !fenetre.current) return
      const el = [...fenetre.current.querySelectorAll<HTMLElement>(FOCALISABLES)]
      if (el.length === 0) return
      const premier = el[0], dernier = el[el.length - 1]
      const actif = document.activeElement
      if (!fenetre.current.contains(actif)) { e.preventDefault(); premier.focus() }
      else if (e.shiftKey && actif === premier) { e.preventDefault(); dernier.focus() }
      else if (!e.shiftKey && actif === dernier) { e.preventDefault(); premier.focus() }
    }
    window.addEventListener('keydown', surTouche)
    return () => { window.removeEventListener('keydown', surTouche); precedent?.focus?.() }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const garde = (action: () => void) => () => { if (clicAccepte(ouvertA.current, Date.now())) action() }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={garde(onAnnuler)}>
      <div ref={fenetre} className="bg-white rounded-lg shadow-xl max-w-md w-full p-5 max-h-[90vh] overflow-y-auto"
        role="alertdialog" aria-modal="true" aria-labelledby="confirmation-sortie-titre"
        onClick={e => e.stopPropagation()}>
        <h2 id="confirmation-sortie-titre" className="text-lg font-bold mb-2 flex items-center gap-2">🌐 {titre}</h2>
        <div className="text-sm text-gray-600 mb-3">{message}</div>
        <div className="text-xs text-gray-500 mb-4">{pied ?? <PiedParDefaut destination={destination} />}</div>
        <div className="flex justify-end gap-2">
          <button type="button" ref={annuler} onClick={garde(onAnnuler)} disabled={occupe}
            className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">Annuler</button>
          <button type="button" onClick={garde(onConfirmer)} disabled={occupe} aria-busy={occupe}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-60">
            {occupe ? 'En cours…' : 'Continuer'}
          </button>
        </div>
      </div>
    </div>
  )
}
