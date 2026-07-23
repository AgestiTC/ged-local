/**
 * GoogleDriveAccounts — connexion et gestion des comptes Google Drive
 * ===================================================================
 * Sous les identifiants de l'app OAuth : un bouton « Connecter un compte » lance le flux OAuth
 * (redirection navigateur → consentement Google → callback qui crée la Source), et la liste des
 * comptes déjà connectés avec indexation / suppression.
 *
 * Prérequis : Client ID/Secret saisis ET ENREGISTRÉS (le flux les lit en base).
 */
import { useCallback, useEffect, useState } from 'react'
import { Cloud, Plus, Trash2, FolderSync, Loader2 } from 'lucide-react'
import { connectorsApi, extractApiError, type CompteConnecteur } from '../../api'
import { useToast } from '../common/Toast'

export default function GoogleDriveAccounts({ clientConfigured }: { clientConfigured: boolean }) {
  const toast = useToast()
  const [comptes, setComptes] = useState<CompteConnecteur[]>([])
  const [busy, setBusy] = useState(false)

  const charger = useCallback(() => {
    connectorsApi.comptes().then(cs => setComptes(cs.filter(c => c.type === 'gdrive'))).catch(() => {})
  }, [])
  useEffect(() => { charger() }, [charger])

  const connecter = async () => {
    setBusy(true)
    try {
      const { url } = await connectorsApi.oauthStart('Google Drive')
      window.location.href = url   // redirige vers le consentement Google
    } catch (e) {
      toast.error(extractApiError(e, 'Connexion impossible — vérifie le Client ID/Secret enregistrés.'))
      setBusy(false)
    }
  }

  const indexer = async (id: string) => {
    try { await connectorsApi.index(id, '/'); toast.success('Indexation du Drive lancée (tâche durable)') }
    catch (e) { toast.error(extractApiError(e, 'Indexation impossible')) }
  }
  const supprimer = async (id: string) => {
    if (!confirm('Déconnecter ce compte Google et retirer ses documents de l\'index ?')) return
    try { await connectorsApi.remove(id); charger() }
    catch (e) { toast.error(extractApiError(e, 'Suppression impossible')) }
  }

  return (
    <div className="space-y-2 pt-1">
      <button type="button" onClick={connecter} disabled={busy || !clientConfigured}
        title={clientConfigured ? 'Ouvre le consentement Google' : 'Renseigne et enregistre d\'abord le Client ID / Secret'}
        className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-40">
        {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Connecter un compte Google
      </button>
      {!clientConfigured && (
        <p className="text-xs text-amber-600">Renseigne et <strong>enregistre</strong> le Client ID / Secret ci-dessus avant de connecter un compte.</p>
      )}

      {comptes.length > 0 && (
        <ul className="space-y-1.5">
          {comptes.map(c => (
            <li key={c.id} className="flex items-center gap-2 border border-gray-200 rounded-lg p-2 text-sm">
              <Cloud size={15} className="text-sky-600 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="font-medium truncate">{c.libelle}</p>
                <p className="text-xs text-gray-400 truncate">{c.identifiant}</p>
              </div>
              <button type="button" onClick={() => indexer(c.id)} title="Indexer ce Drive"
                className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-sky-200 text-sky-600 hover:bg-sky-50">
                <FolderSync size={12} /> Indexer
              </button>
              <button type="button" onClick={() => supprimer(c.id)} title="Déconnecter" className="p-1 text-gray-400 hover:text-red-500">
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
