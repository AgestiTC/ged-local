/**
 * MessageErreurIa — message PERSISTANT d'une bascule refusée (403/422…) ou d'un enregistrement refusé :
 * un toast de 4 s ne suffit pas pour une décision de sortie internet. Reste affiché, sous l'en-tête, jusqu'à
 * ce qu'on le ferme ou qu'une bascule réussisse. Le message est celui du serveur, tel quel.
 */
import { X } from 'lucide-react'
import { useIaDestinationStore } from '../../stores/iaDestinationStore'

export function MessageErreurIaVue({ message, onFermer }: { message: string | null; onFermer: () => void }) {
  if (!message) return null
  return (
    <div role="alert" className="shrink-0 flex items-start gap-2 px-3 py-1.5 bg-red-50 border-b border-red-200 text-red-900 text-xs sm:text-sm">
      <span className="flex-1 min-w-0"><strong>IA LOCAL / IA GECO :</strong> {message}</span>
      <button type="button" onClick={onFermer} aria-label="Fermer ce message"
        className="shrink-0 p-0.5 rounded hover:bg-red-100"><X size={14} /></button>
    </div>
  )
}

export default function MessageErreurIa() {
  const erreur = useIaDestinationStore(s => s.erreur)
  return <MessageErreurIaVue message={erreur} onFermer={() => useIaDestinationStore.getState().effacerErreur()} />
}
