/**
 * Réglages « IA GECO » de la page Paramètres : le modèle GECO utilisé (près de la liste « Modèles
 * GECO ») et l'entrée de la section « Demandes Mise à jour internet ». La bascule est LA MÊME que
 * celle de l'en-tête (même composant, même confirmation).
 */
import { useIaDestinationStore } from '../../stores/iaDestinationStore'
import { modelesGecoChoisissables } from '../../utils/iaDestination'
import type { ExternesEtat, ModeleExterne } from '../../api'
import { useToast } from '../common/Toast'
import BoutonIaDestination from './BoutonIaDestination'

interface Props { externes: ModeleExterne[]; externesEtat: ExternesEtat }

/** Choix du « modèle GECO utilisé » + état du bouton. Désactivé tant que la liste n'est pas disponible. */
export function ReglageIaGeco({ externes, externesEtat }: Props) {
  const gecoModele = useIaDestinationStore(s => s.gecoModele)
  const toast = useToast()
  const disponible = externesEtat === 'disponible'
  const choix = modelesGecoChoisissables(externes)
  const absent = !!gecoModele && !choix.some(m => m.name === gecoModele)

  const choisir = async (modele: string) => {
    const r = await useIaDestinationStore.getState().definirGecoModele(modele)
    if (r.ok) toast.success(r.message)
    else toast.error(r.message)   // 422 du serveur affiché tel quel
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="w-4 h-4 shrink-0" aria-hidden="true" />
        <label htmlFor="geco-modele" className="text-sm w-24 shrink-0 text-gray-600 leading-tight">
          Modèle GECO utilisé
          <span className="block text-[10px] font-semibold tracking-wide text-gray-400">IA GECO</span>
        </label>
        <select id="geco-modele" value={gecoModele} disabled={!disponible}
          onChange={e => { void choisir(e.target.value) }}
          title={disponible ? 'Modèle utilisé par « Auto » quand le bouton est sur IA GECO' : "La liste des modèles GECO n'est pas disponible"}
          className="flex-1 min-w-0 text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:bg-gray-50 disabled:text-gray-400">
          <option value="">{disponible ? 'Aucun — choisir un modèle' : 'Liste GECO indisponible'}</option>
          {absent && <option value={gecoModele}>{gecoModele} (absent de la liste actuelle)</option>}
          {choix.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
        </select>
        <BoutonIaDestination listeDisponible={disponible} />
      </div>
      <p className="text-[11px] text-gray-400 ml-6">
        Le bouton « IA LOCAL / IA GECO » (aussi dans l'en-tête) envoie les demandes interactives chez GECO, par
        internet, après confirmation. Les modèles d'embeddings ne sont jamais proposés.
      </p>
    </div>
  )
}

/** Entrée de « Demandes Mise à jour internet » : même forme que les entrées existantes (texte + bouton). */
export function EntreeInternetIaGeco({ externesEtat }: { externesEtat: ExternesEtat }) {
  return (
    <div className="flex items-center justify-between px-4 py-3 gap-4">
      <div>
        <p className="text-sm font-medium text-gray-700">IA GECO — demandes interactives par internet</p>
        <p className="text-xs text-gray-400 mt-0.5">
          Une fois activée (et confirmée), la discussion, les rapports
          et les comparatifs envoient <strong>vos questions, extraits et documents joints</strong> chez GECO, tant que
          le bandeau « IA GECO activée » est affiché. L'indexation, l'enrichissement, la recherche sémantique et la
          lecture d'images ne partent <strong>jamais</strong>.
        </p>
      </div>
      <BoutonIaDestination listeDisponible={externesEtat === 'disponible'} />
    </div>
  )
}
