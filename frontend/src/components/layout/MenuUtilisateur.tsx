/**
 * Menu utilisateur de l'en-tête : nom, rôle, « Se déconnecter ».
 * N'apparaît QUE si une personne est connectée (authentification éteinte : rien, comme avant).
 */
import { useState } from 'react'
import { LogOut, UserRound } from 'lucide-react'
import { useAuthStore } from '../../stores/authStore'

export default function MenuUtilisateur() {
  const utilisateur = useAuthStore(s => s.utilisateur)
  const authActive = useAuthStore(s => s.authActive)
  const deconnecter = useAuthStore(s => s.deconnecter)
  const [enCours, setEnCours] = useState(false)
  if (!authActive || !utilisateur) return null

  const nom = utilisateur.nom || utilisateur.identifiant || 'Utilisateur'
  return (
    <span className="flex items-center gap-1.5" data-testid="menu-utilisateur">
      <UserRound size={15} className="text-gray-400" />
      <span className="hidden sm:inline text-gray-700 font-medium max-w-[10rem] truncate" title={utilisateur.email ?? nom}>{nom}</span>
      <span className="hidden sm:inline text-[11px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-500">
        {utilisateur.role === 'admin' ? 'Administrateur' : 'Utilisateur'}
      </span>
      <button type="button" disabled={enCours} title="Se déconnecter" aria-label="Se déconnecter"
        onClick={() => { setEnCours(true); void deconnecter() }}
        className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md disabled:opacity-50">
        <LogOut size={15} />
      </button>
    </span>
  )
}
