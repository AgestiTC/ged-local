/**
 * Paramètres › Utilisateurs (admins, visible seulement si l'authentification est active)
 * ======================================================================================
 * Les personnes viennent du SSO du NAS (fiche créée à la première connexion). Pas de création de
 * compte ici, et le rôle est LU du groupe du NAS (non modifiable). Deux actions, toutes deux
 * confirmées et journalisées côté serveur :
 *   - « Déconnecter partout » : supprime toutes les sessions de la personne ;
 *   - « Bloquer / Débloquer » : refus même si le SSO accepte (frein d'urgence).
 */
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Ban, LogOut, RefreshCw, ShieldCheck } from 'lucide-react'
import { authApi, type PersonneAuth } from '../../api'
import { useAuthStore } from '../../stores/authStore'
import { suspensionActive } from '../../utils/acces'
import { useToast } from '../common/Toast'
import LoadingSpinner from '../common/LoadingSpinner'

type Action = { type: 'deconnecter' | 'bloquer' | 'debloquer'; personne: PersonneAuth }

function date(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '—' : d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
}

function nomPersonne(p: PersonneAuth): string {
  return p.nom || p.identifiant || 'cette personne'
}

function messageErreur(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' ? d : "L'action a échoué."
}

export default function UtilisateursAdmin() {
  const toast = useToast()
  const moi = useAuthStore(s => s.utilisateur)
  const suspensionJusqua = useAuthStore(s => s.suspensionJusqua)
  // Accès de secours sans identité : le serveur exige une session admin pour gérer les personnes.
  const sansIdentite = !moi && suspensionActive(suspensionJusqua)
  const titreId = useId()
  const annulerRef = useRef<HTMLButtonElement>(null)
  const declencheurRef = useRef<HTMLElement | null>(null)
  const [personnes, setPersonnes] = useState<PersonneAuth[] | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [confirmation, setConfirmation] = useState<Action | null>(null)
  const [enCours, setEnCours] = useState(false)

  const charger = useCallback(async () => {
    try {
      setPersonnes(await authApi.utilisateurs())
      setErreur(null)
    } catch (e) {
      setErreur(messageErreur(e))
    }
  }, [])

  useEffect(() => { if (!sansIdentite) void charger() }, [charger, sansIdentite])

  // Modale : focus initial sur « Annuler », Échap ferme (sauf pendant l'action), le focus revient au déclencheur.
  const fermer = useCallback(() => {
    setConfirmation(null)
    declencheurRef.current?.focus()
  }, [])
  useEffect(() => {
    if (!confirmation) return
    annulerRef.current?.focus()
    const surTouche = (e: KeyboardEvent) => { if (e.key === 'Escape' && !enCours) fermer() }
    document.addEventListener('keydown', surTouche)
    return () => document.removeEventListener('keydown', surTouche)
  }, [confirmation, enCours, fermer])
  const demander = (a: Action) => {
    declencheurRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setConfirmation(a)
  }

  const executer = async () => {
    if (!confirmation) return
    const { type, personne } = confirmation
    setEnCours(true)
    try {
      if (type === 'deconnecter') {
        const r = await authApi.deconnecter(personne.id)
        const n = r.sessions_supprimees
        toast.success(`${nomPersonne(personne)} déconnecté·e (${n} session${n > 1 ? 's' : ''} coupée${n > 1 ? 's' : ''}).`)
      } else {
        await authApi.bloquer(personne.id, type === 'bloquer')
        toast.success(type === 'bloquer' ? `${nomPersonne(personne)} est bloqué·e dans Matothèque.` : `${nomPersonne(personne)} est débloqué·e.`)
      }
    } catch (e) {
      toast.error(messageErreur(e))
    } finally {
      setEnCours(false)
      fermer()
      void charger()
    }
  }

  const estMoi = (p: PersonneAuth) => !!moi?.id && moi.id === p.id

  if (sansIdentite) {
    return (
      <p role="status" className="pt-1 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
        Accès de secours en cours : identifiez-vous par le SSO pour gérer les personnes.
      </p>
    )
  }

  return (
    <div className="pt-1 space-y-3">
      <p className="text-xs text-gray-500">
        Les comptes et les rôles viennent du <strong>NAS</strong> (groupes <code>matotheque-admin</code> et{' '}
        <code>matotheque-utilisateurs</code>) : ils ne se modifient pas ici. <strong>Retirer quelqu'un = le sortir
        du groupe sur le NAS</strong> (plus de connexion possible), puis « Déconnecter partout » pour couper ses
        sessions en cours. « Bloquer » est un frein d'urgence : refus même si le NAS accepte.
      </p>
      <div className="flex justify-end">
        <button type="button" onClick={() => void charger()}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-gray-300 rounded-lg hover:bg-gray-50">
          <RefreshCw size={13} /> Actualiser
        </button>
      </div>

      {erreur && <p role="alert" className="text-sm text-red-700">{erreur}</p>}
      {!personnes && !erreur && <LoadingSpinner label="Chargement…" />}
      {personnes && personnes.length === 0 && (
        <p className="text-sm text-gray-500">Personne ne s'est encore connecté : les fiches se créent à la première connexion.</p>
      )}
      {personnes && personnes.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-gray-500 border-b border-gray-200">
              <tr>
                <th scope="col" className="py-2 pr-3">Personne</th><th scope="col" className="pr-3">Rôle (lu du NAS)</th>
                <th scope="col" className="pr-3">Première connexion</th><th scope="col" className="pr-3">Dernière connexion</th>
                <th scope="col" className="pr-3">Sessions</th><th scope="col" className="pr-3">État</th><th scope="col" className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {personnes.map(p => (
                <tr key={p.id} className="border-b border-gray-100 align-top">
                  <td className="py-2 pr-3">
                    <div className="font-medium text-gray-800">{p.nom || p.identifiant || '—'}</div>
                    <div className="text-xs text-gray-400">{p.identifiant}{p.email ? ` · ${p.email}` : ''}</div>
                  </td>
                  <td className="pr-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${p.role === 'admin' ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600'}`}>
                      {p.role === 'admin' ? 'Administrateur' : 'Utilisateur'}
                    </span>
                  </td>
                  <td className="pr-3 text-xs text-gray-500">{date(p.premiere_connexion)}</td>
                  <td className="pr-3 text-xs text-gray-500">{date(p.derniere_connexion)}</td>
                  <td className="pr-3">{p.sessions}</td>
                  <td className="pr-3">
                    {p.bloque
                      ? <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700">Bloqué</span>
                      : <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">Actif</span>}
                  </td>
                  <td className="text-right whitespace-nowrap space-x-1.5">
                    <button type="button" disabled={p.sessions === 0}
                      title={p.sessions === 0 ? 'Aucune session ouverte' : 'Couper toutes ses sessions'}
                      onClick={() => demander({ type: 'deconnecter', personne: p })}
                      className="inline-flex items-center gap-1 px-2 py-1 text-xs border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40">
                      <LogOut size={12} /> Déconnecter partout
                    </button>
                    {p.bloque ? (
                      <button type="button" onClick={() => demander({ type: 'debloquer', personne: p })}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs border border-green-300 text-green-700 rounded-lg hover:bg-green-50">
                        <ShieldCheck size={12} /> Débloquer
                      </button>
                    ) : (
                      <button type="button" disabled={estMoi(p)}
                        title={estMoi(p) ? 'Vous ne pouvez pas vous bloquer vous-même' : 'Refuser sa connexion et couper ses sessions'}
                        onClick={() => demander({ type: 'bloquer', personne: p })}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs border border-red-300 text-red-700 rounded-lg hover:bg-red-50 disabled:opacity-40">
                        <Ban size={12} /> Bloquer
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {confirmation && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
          onClick={() => !enCours && fermer()}>
          <div role="dialog" aria-modal="true" aria-labelledby={titreId} className="bg-white rounded-lg shadow-xl max-w-md w-full p-5"
            onClick={e => e.stopPropagation()}>
            <h2 id={titreId} className="text-lg font-bold mb-2">
              {confirmation.type === 'deconnecter' ? 'Déconnecter partout ?'
                : confirmation.type === 'bloquer' ? 'Bloquer dans Matothèque ?' : 'Débloquer ?'}
            </h2>
            <p className="text-sm text-gray-600 mb-4">
              {confirmation.type === 'deconnecter' && <>Toutes les sessions de <strong>{nomPersonne(confirmation.personne)}</strong> seront coupées ; la personne pourra se reconnecter.</>}
              {confirmation.type === 'bloquer' && <><strong>{nomPersonne(confirmation.personne)}</strong> sera refusé·e à la connexion même si le NAS accepte, et ses sessions seront coupées.</>}
              {confirmation.type === 'debloquer' && <><strong>{nomPersonne(confirmation.personne)}</strong> pourra de nouveau se connecter.</>}
              {' '}L'action est inscrite au journal d'activité.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" ref={annulerRef} disabled={enCours} onClick={fermer}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50">Annuler</button>
              <button type="button" disabled={enCours} onClick={() => void executer()}
                className={`px-4 py-2 text-white text-sm rounded-lg disabled:opacity-60 ${confirmation.type === 'debloquer' ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'}`}>
                Confirmer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
