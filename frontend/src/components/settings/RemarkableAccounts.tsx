/**
 * RemarkableAccounts — appairage et gestion des comptes reMarkable Cloud
 * ======================================================================
 * Appairage par **code à usage unique** (my.remarkable.com/device/desktop) → device token
 * durable (chiffré). Liste des comptes avec pastille de connexion, indexation (tâche durable)
 * et suppression. L'API cloud reMarkable est non officielle → à valider sur un compte réel.
 */
import { useCallback, useEffect, useState } from 'react'
import { Tablet, Plus, Trash2, FolderSync, Loader2, ExternalLink, Wifi } from 'lucide-react'
import { connectorsApi, extractApiError, type CompteConnecteur } from '../../api'
import { clsx } from 'clsx'
import { useToast } from '../common/Toast'

export default function RemarkableAccounts() {
  const toast = useToast()
  const [comptes, setComptes] = useState<CompteConnecteur[]>([])
  const [statut, setStatut] = useState<Record<string, boolean | null>>({})
  const [showForm, setShowForm] = useState(false)
  const [code, setCode] = useState('')
  const [libelle, setLibelle] = useState('reMarkable')
  const [busy, setBusy] = useState(false)

  const tester = useCallback((id: string) => {
    setStatut(s => ({ ...s, [id]: null }))
    connectorsApi.test(id)
      .then(r => setStatut(s => ({ ...s, [id]: r.ok })))
      .catch(() => setStatut(s => ({ ...s, [id]: false })))
  }, [])

  const charger = useCallback(() => {
    connectorsApi.comptes().then(cs => {
      const rm = cs.filter(c => c.type === 'remarkable')
      setComptes(rm)
      rm.forEach(c => tester(c.id))
    }).catch(() => {})
  }, [tester])
  useEffect(() => { charger() }, [charger])

  const appairer = async () => {
    if (code.trim().length < 6) { toast.error('Saisis le code d\'appairage (8 caractères)'); return }
    setBusy(true)
    try {
      await connectorsApi.remarkablePair(code.trim(), libelle.trim() || 'reMarkable')
      toast.success('Compte reMarkable appairé ✓')
      setCode(''); setShowForm(false); charger()
    } catch (e) {
      toast.error(extractApiError(e, 'Appairage impossible — code périmé ? (usage unique)'))
    } finally { setBusy(false) }
  }

  const indexer = async (id: string) => {
    try { await connectorsApi.index(id, '/'); toast.success('Indexation reMarkable lancée (tâche durable)') }
    catch (e) { toast.error(extractApiError(e, 'Indexation impossible')) }
  }
  const supprimer = async (id: string) => {
    if (!confirm('Déconnecter ce compte reMarkable et retirer ses documents de l\'index ?')) return
    try { await connectorsApi.remove(id); charger() }
    catch (e) { toast.error(extractApiError(e, 'Suppression impossible')) }
  }

  return (
    <div className="space-y-2 pt-1">
      {!showForm ? (
        <button type="button" onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-slate-700 text-white hover:bg-slate-800">
          <Plus size={14} /> Appairer un reMarkable
        </button>
      ) : (
        <div className="border border-gray-200 rounded-lg p-3 space-y-2 bg-gray-50/50">
          <p className="text-xs text-gray-500">
            1. Ouvre <a href="https://my.remarkable.com/device/desktop" target="_blank" rel="noopener noreferrer"
              className="text-slate-700 underline inline-flex items-center gap-0.5">my.remarkable.com/device/desktop <ExternalLink size={10} /></a> (connecté à ton compte)
            → 2. recopie le <strong>code à usage unique</strong> affiché ci-dessous.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input value={code} onChange={e => setCode(e.target.value)} placeholder="Code d'appairage (ex. abcdefgh)"
              className="text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono tracking-widest focus:outline-none focus:ring-1 focus:ring-slate-400" />
            <input value={libelle} onChange={e => setLibelle(e.target.value)} placeholder="Nom du compte"
              className="text-sm border border-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-slate-400" />
          </div>
          <div className="flex items-center justify-end gap-2">
            <button type="button" onClick={() => setShowForm(false)} className="text-sm px-3 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">Annuler</button>
            <button type="button" onClick={appairer} disabled={busy}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-slate-700 text-white hover:bg-slate-800 disabled:opacity-50">
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Wifi size={14} />} Appairer
            </button>
          </div>
        </div>
      )}

      {comptes.length > 0 && (
        <ul className="space-y-1.5">
          {comptes.map(c => (
            <li key={c.id} className="flex items-center gap-2 border border-gray-200 rounded-lg p-2 text-sm">
              <Tablet size={15} className="text-slate-600 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="font-medium truncate flex items-center gap-1.5">
                  <span title={statut[c.id] === true ? 'Connexion établie' : statut[c.id] === false ? 'Connexion à rétablir (ré-appaire)' : 'Vérification…'}
                    className={clsx('w-2 h-2 rounded-full inline-block shrink-0',
                      statut[c.id] === true ? 'bg-green-500' : statut[c.id] === false ? 'bg-red-500' : 'bg-gray-300 animate-pulse')} />
                  {c.libelle}
                </p>
              </div>
              <button type="button" onClick={() => indexer(c.id)} title="Indexer ce reMarkable"
                className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50">
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
