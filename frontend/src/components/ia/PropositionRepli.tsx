/**
 * PropositionRepli — sous un message du chat dont l'IA locale n'a pas répondu : propose de passer
 * sur IA GECO. N'agit JAMAIS seule : le bouton ouvre la même confirmation que l'en-tête.
 */
import { Globe } from 'lucide-react'
import { useIaDestinationStore } from '../../stores/iaDestinationStore'
import { useAuthStore } from '../../stores/authStore'
import { estAdmin } from '../../utils/acces'
import { proposerRepli } from '../../utils/iaDestination'
import { useActionsIa } from './useActionsIa'

export function PropositionRepliVue({ visible, onAccepter }: { visible: boolean; onAccepter: () => void }) {
  if (!visible) return null
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5">
      <Globe size={13} className="shrink-0" aria-hidden="true" />
      <span>L'IA locale ne répond pas — passer sur IA GECO ?</span>
      <button type="button" onClick={onAccepter}
        className="px-2 py-0.5 rounded-md border border-amber-400 bg-white font-semibold hover:bg-amber-100">
        Passer sur IA GECO…
      </button>
    </div>
  )
}

/** `erreurIaLocale` : champ structuré du message (posé par le store) ; `enCours` : un flux est en cours. */
export default function PropositionRepli({ erreurIaLocale, enCours }: { erreurIaLocale: boolean; enCours: boolean }) {
  const destination = useIaDestinationStore(s => s.destination)
  const gecoModele = useIaDestinationStore(s => s.gecoModele)
  const admin = useAuthStore(s => estAdmin(s))
  const { versGeco } = useActionsIa()
  return (
    <PropositionRepliVue
      visible={proposerRepli({ destination, gecoModele, admin, enCours, erreurIaLocale })}
      onAccepter={() => versGeco()} />
  )
}
