/**
 * ConfirmationBasculeGeco — la fenêtre de confirmation de sortie internet de la bascule vers GECO.
 * Montée UNE fois (MainLayout) et pilotée par le store : l'en-tête, les Paramètres et le repli du
 * chat ouvrent la même. La bascule n'écrit qu'après « Continuer », et avec le modèle ANNONCÉ ici
 * (si le modèle a changé entre-temps, le store rouvre la fenêtre avec le nouveau, sans envoyer).
 */
import { useIaDestinationStore } from '../../stores/iaDestinationStore'
import { confirmationBascule } from '../../utils/iaDestination'
import { ConfirmationSortieInternet } from '../common/ConfirmationSortieInternet'
import { useToast } from '../common/Toast'

export default function ConfirmationBasculeGeco() {
  const demande = useIaDestinationStore(s => s.demande)
  const occupe = useIaDestinationStore(s => s.enCours)
  const toast = useToast()
  if (!demande) return null
  const c = confirmationBascule(demande.modele)
  const confirmer = async () => {
    const r = await useIaDestinationStore.getState().basculer('geco', { confirme: true, modele: demande.modele })
    if (r.ok) toast.success(r.message)
    else toast.error(r.message)   // détail du serveur (403/422…) tel quel ; il reste aussi affiché dans la bande d'erreur
  }
  return (
    <ConfirmationSortieInternet
      key={demande.modele}   // modèle changé → fenêtre rouverte (focus et délai anti-clic repartent)
      titre={c.titre}
      message={(
        <div className="space-y-2">
          <p>{c.envoye}</p>
          <p>{c.jamaisEnvoye}</p>
          <p><strong>{c.modele}</strong></p>
          <p>{c.bandeau}</p>
        </div>
      )}
      pied={<p>Seules les demandes des administrateurs partent chez GECO : les autres utilisateurs restent en 100 % local. Le réglage dure jusqu'au retour sur IA locale.</p>}
      occupe={occupe}
      onAnnuler={() => useIaDestinationStore.getState().annulerBascule()}
      onConfirmer={confirmer}
    />
  )
}
