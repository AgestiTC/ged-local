/**
 * WebDavAccounts — connexion et gestion des comptes WebDAV
 * ========================================================
 * Connecteur générique (Nextcloud / ownCloud / kDrive / Synology WebDAV / mod_dav…) en
 * **HTTP Basic** — pas d'OAuth. Un formulaire crée un compte (URL de base + identifiants,
 * secret chiffré côté backend), puis la liste des comptes avec pastille de connexion,
 * indexation (tâche durable) et suppression.
 */
import { useCallback, useEffect, useState } from 'react'
import { Server, Plus, Trash2, FolderSync, Loader2, Wifi } from 'lucide-react'
import { connectorsApi, extractApiError, type CompteConnecteur } from '../../api'
import { clsx } from 'clsx'
import { useToast } from '../common/Toast'

export default function WebDavAccounts() {
  const toast = useToast()
  const [comptes, setComptes] = useState<CompteConnecteur[]>([])
  const [statut, setStatut] = useState<Record<string, boolean | null>>({})
  const [showForm, setShowForm] = useState(false)
  const [busy, setBusy] = useState(false)

  // Champs du formulaire de connexion
  const [libelle, setLibelle] = useState('')
  const [hote, setHote] = useState('')
  const [identifiant, setIdentifiant] = useState('')
  const [motDePasse, setMotDePasse] = useState('')
  const [cheminBase, setCheminBase] = useState('')

  const tester = useCallback((id: string) => {
    setStatut(s => ({ ...s, [id]: null }))
    connectorsApi.test(id)
      .then(r => setStatut(s => ({ ...s, [id]: r.ok })))
      .catch(() => setStatut(s => ({ ...s, [id]: false })))
  }, [])

  const charger = useCallback(() => {
    connectorsApi.comptes().then(cs => {
      const dav = cs.filter(c => c.type === 'webdav')
      setComptes(dav)
      dav.forEach(c => tester(c.id))
    }).catch(() => {})
  }, [tester])
  useEffect(() => { charger() }, [charger])

  const connecter = async () => {
    if (!libelle.trim() || !hote.trim() || !identifiant.trim() || !motDePasse) {
      toast.error('Libellé, URL, utilisateur et mot de passe sont requis')
      return
    }
    setBusy(true)
    try {
      const compte = await connectorsApi.createCredential({
        type: 'webdav', libelle: libelle.trim(), hote: hote.trim(),
        identifiant: identifiant.trim(), mot_de_passe: motDePasse,
        chemin_base: cheminBase.trim() || undefined,
      })
      // Vérifie tout de suite la connexion (pastille) — feedback immédiat.
      try {
        const r = await connectorsApi.test(compte.id)
        if (r.ok) toast.success('Compte WebDAV connecté ✓')
        else toast.error('Compte créé mais la connexion a échoué — vérifie URL / identifiants')
      } catch { toast.error('Compte créé mais la connexion a échoué — vérifie URL / identifiants') }
      setLibelle(''); setHote(''); setIdentifiant(''); setMotDePasse(''); setCheminBase('')
      setShowForm(false); charger()
    } catch (e) {
      toast.error(extractApiError(e, 'Création du compte impossible'))
    } finally { setBusy(false) }
  }

  const indexer = async (id: string) => {
    try { await connectorsApi.index(id, '/'); toast.success('Indexation WebDAV lancée (tâche durable)') }
    catch (e) { toast.error(extractApiError(e, 'Indexation impossible')) }
  }
  const supprimer = async (id: string) => {
    if (!confirm('Déconnecter ce compte WebDAV et retirer ses documents de l\'index ?')) return
    try { await connectorsApi.remove(id); charger() }
    catch (e) { toast.error(extractApiError(e, 'Suppression impossible')) }
  }

  return (
    <div className="space-y-2 pt-1">
      {!showForm ? (
        <button type="button" onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-sky-600 text-white hover:bg-sky-700">
          <Plus size={14} /> Connecter un serveur WebDAV
        </button>
      ) : (
        <div className="border border-gray-200 rounded-lg p-3 space-y-2 bg-gray-50/50">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input value={libelle} onChange={e => setLibelle(e.target.value)} placeholder="Nom (ex. Nextcloud perso)"
              className="text-sm border border-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-sky-400" />
            <input value={identifiant} onChange={e => setIdentifiant(e.target.value)} placeholder="Utilisateur"
              className="text-sm border border-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-sky-400" />
          </div>
          <input value={hote} onChange={e => setHote(e.target.value)}
            placeholder="URL de base (ex. https://cloud.exemple.fr/remote.php/dav/files/jean/)"
            className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-sky-400" />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input type="password" value={motDePasse} onChange={e => setMotDePasse(e.target.value)}
              placeholder="Mot de passe (ou mot de passe d'application)"
              className="text-sm border border-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-sky-400" />
            <input value={cheminBase} onChange={e => setCheminBase(e.target.value)} placeholder="Dossier de départ (facultatif, ex. /Documents)"
              className="text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-sky-400" />
          </div>
          <p className="text-xs text-gray-400">
            Astuce : Nextcloud/ownCloud → URL <code>…/remote.php/dav/files/&lt;user&gt;/</code> et un
            <strong> mot de passe d'application</strong>. Synology WebDAV → <code>https://nas:5006/</code>.
          </p>
          <div className="flex items-center gap-2 justify-end">
            <button type="button" onClick={() => setShowForm(false)} className="text-sm px-3 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">Annuler</button>
            <button type="button" onClick={connecter} disabled={busy}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50">
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Wifi size={14} />} Connecter et tester
            </button>
          </div>
        </div>
      )}

      {comptes.length > 0 && (
        <ul className="space-y-1.5">
          {comptes.map(c => (
            <li key={c.id} className="flex items-center gap-2 border border-gray-200 rounded-lg p-2 text-sm">
              <Server size={15} className="text-sky-600 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="font-medium truncate flex items-center gap-1.5">
                  <span title={statut[c.id] === true ? 'Connexion établie' : statut[c.id] === false ? 'Connexion à rétablir (vérifie URL/identifiants)' : 'Vérification…'}
                    className={clsx('w-2 h-2 rounded-full inline-block shrink-0',
                      statut[c.id] === true ? 'bg-green-500' : statut[c.id] === false ? 'bg-red-500' : 'bg-gray-300 animate-pulse')} />
                  {c.libelle}
                </p>
                <p className="text-xs text-gray-400 truncate">{c.identifiant}{c.chemin_base ? ` · ${c.chemin_base}` : ''}</p>
              </div>
              <button type="button" onClick={() => indexer(c.id)} title="Indexer ce serveur"
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
