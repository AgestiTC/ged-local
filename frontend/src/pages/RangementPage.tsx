/**
 * Page Rangement (administrateur) — l'inventaire des disques de la maison.
 *  - « Carte » : où est la place, par emplacement puis dossier par dossier ;
 *  - « Plan de classement » : où devrait aller chaque grand dossier (étape 9) ;
 *  - « Postes » : les PC qui envoient leur inventaire (agent) ou un export WizTree.
 * Les copies sur disque sont dans « Doublons » (une seule logique, étape 6) : lien ci-dessous.
 * Rien ici ne déplace de fichier : ranger viendra avec le plan de classement (étapes 8 à 10).
 */
import { Link, useSearchParams } from 'react-router-dom'
import { HardDrive } from 'lucide-react'
import { clsx } from 'clsx'
import CarteInventaire from '../components/rangement/CarteInventaire'
import PostesInventaire from '../components/rangement/PostesInventaire'
import PlanClassement from '../components/rangement/PlanClassement'

type Onglet = 'carte' | 'plan' | 'postes'

export default function RangementPage() {
  // L'onglet est dans l'adresse : un lien de la cloche (« /rangement?onglet=plan ») ouvre le bon.
  const [params, setParams] = useSearchParams()
  const demande = params.get('onglet')
  const onglet: Onglet = demande === 'plan' || demande === 'postes' ? demande : 'carte'
  const setOnglet = (k: Onglet) => setParams(k === 'carte' ? {} : { onglet: k }, { replace: true })
  return (
    <div className="max-w-7xl mx-auto px-3 sm:px-6 py-6">
      <h1 className="text-2xl font-bold flex items-center gap-2"><HardDrive size={22} className="text-blue-600" /> Rangement</h1>
      <p className="text-sm text-gray-500 mb-4">
        Inventaire des disques : ce qu'il y a, où, et ce qui grossit. Lu sans jamais rien modifier.
        Les fichiers en plusieurs exemplaires sont dans <Link to="/doublons" className="text-blue-600 hover:underline">Doublons › Copies sur disque</Link>.
      </p>
      <div className="flex gap-1 mb-4 border-b border-gray-200" role="tablist">
        {([['carte', 'Carte'], ['plan', 'Plan de classement'], ['postes', 'Postes']] as const).map(([k, libelle]) => (
          <button key={k} type="button" role="tab" aria-selected={onglet === k} onClick={() => setOnglet(k)}
            className={clsx('px-4 py-2 text-sm border-b-2 -mb-px',
              onglet === k ? 'border-blue-600 text-blue-700 font-medium' : 'border-transparent text-gray-500 hover:text-gray-700')}>
            {libelle}
          </button>
        ))}
      </div>
      {onglet === 'carte' ? <CarteInventaire /> : onglet === 'plan' ? <PlanClassement /> : <PostesInventaire />}
    </div>
  )
}
