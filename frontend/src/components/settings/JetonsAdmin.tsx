/**
 * Paramètres › Utilisateurs › Jetons d'automates (admins) — plan d'authentification, étape 4
 * ==========================================================================================
 * Un automate (n8n, script) n'a pas de compte SSO : il présente `Authorization: Bearer mato_…`.
 * Le jeton en clair n'est montré QU'UNE fois, juste après la création (seule son empreinte est
 * gardée). « Révoquer » est définitif. Rôle = quelles routes ; portée = lecture seule ou écriture.
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Copy, KeyRound, Plus, RefreshCw, XCircle } from 'lucide-react'
import { authApi, type JetonAutomate, type NouveauJeton } from '../../api'
import { useAuthStore } from '../../stores/authStore'
import { suspensionActive } from '../../utils/acces'
import { copierTexte } from '../../utils/clipboard'
import { useToast } from '../common/Toast'
import LoadingSpinner from '../common/LoadingSpinner'

function date(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '—' : d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
}

function messageErreur(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' ? d : "L'action a échoué."
}

const VIDE: NouveauJeton = { nom: '', role: 'utilisateur', portee: 'lecture', expire_jours: 365 }

export default function JetonsAdmin() {
  const toast = useToast()
  const moi = useAuthStore(s => s.utilisateur)
  const suspensionJusqua = useAuthStore(s => s.suspensionJusqua)
  const sansIdentite = !moi && suspensionActive(suspensionJusqua)
  const [jetons, setJetons] = useState<JetonAutomate[] | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [form, setForm] = useState<NouveauJeton>(VIDE)
  const [enCours, setEnCours] = useState(false)
  const [nouveau, setNouveau] = useState<{ nom: string; jeton: string } | null>(null)
  const [aRevoquer, setARevoquer] = useState<string | null>(null)

  const charger = useCallback(async () => {
    try {
      setJetons(await authApi.jetons())
      setErreur(null)
    } catch (e) {
      setErreur(messageErreur(e))
    }
  }, [])

  useEffect(() => { if (!sansIdentite) void charger() }, [charger, sansIdentite])

  if (sansIdentite) return null

  const creer = async (e: FormEvent) => {
    e.preventDefault()
    if (!form.nom.trim()) return
    setEnCours(true)
    try {
      const r = await authApi.creerJeton({ ...form, nom: form.nom.trim() })
      setNouveau({ nom: r.nom, jeton: r.jeton })
      setForm(VIDE)
      void charger()
    } catch (err) {
      toast.error(messageErreur(err))
    } finally {
      setEnCours(false)
    }
  }

  const revoquer = async (j: JetonAutomate) => {
    setEnCours(true)
    try {
      await authApi.revoquerJeton(j.id)
      toast.success(`Jeton « ${j.nom} » révoqué.`)
    } catch (err) {
      toast.error(messageErreur(err))
    } finally {
      setEnCours(false)
      setARevoquer(null)
      void charger()
    }
  }

  const copier = async (texte: string) => {
    if (await copierTexte(texte)) toast.success('Jeton copié.')
    else toast.error('Copie impossible : sélectionnez le jeton et copiez-le à la main.')
  }

  return (
    <div className="mt-6 pt-4 border-t border-gray-200 space-y-3">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-gray-800">
        <KeyRound size={15} className="text-indigo-600" /> Jetons d'automates
      </h3>
      <p className="text-xs text-gray-500">
        Pour n8n ou un script : en-tête <code>Authorization: Bearer mato_…</code>. Le jeton n'est affiché{' '}
        <strong>qu'une seule fois</strong>, à la création : rangez-le dans Bitwarden. Le <strong>rôle</strong> dit quelles
        routes l'automate peut appeler, la <strong>portée</strong> s'il peut écrire. Même « Administrateur », un jeton
        n'atteint que les dossiers surveillés : jamais la configuration, les sauvegardes, les journaux, les sources, la
        passerelle, les personnes ni les données du foyer. Bloquer son créateur le révoque.
      </p>

      {nouveau && (
        <div role="status" className="rounded-lg border border-amber-300 bg-amber-50 p-3 space-y-2">
          <p className="text-sm text-amber-900">
            Jeton « <strong>{nouveau.nom}</strong> » créé. <strong>Copiez-le maintenant</strong> : il ne sera plus jamais affiché.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 min-w-0 break-all text-xs bg-white border border-amber-200 rounded px-2 py-1 select-all">{nouveau.jeton}</code>
            <button type="button" onClick={() => void copier(nouveau.jeton)}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs border border-gray-300 rounded-lg bg-white hover:bg-gray-50">
              <Copy size={12} /> Copier
            </button>
          </div>
          <button type="button" onClick={() => setNouveau(null)} className="text-xs text-amber-900 underline">
            C'est rangé, masquer
          </button>
        </div>
      )}

      <form onSubmit={e => void creer(e)} className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-xs text-gray-600">
          Nom
          <input value={form.nom} maxLength={100} required placeholder="ex. n8n — surveillance des dossiers"
            onChange={e => setForm({ ...form, nom: e.target.value })}
            className="mt-0.5 w-64 px-2 py-1.5 text-sm border border-gray-300 rounded-lg" />
        </label>
        <label className="flex flex-col text-xs text-gray-600">
          Rôle
          <select value={form.role} onChange={e => setForm({ ...form, role: e.target.value as NouveauJeton['role'] })}
            className="mt-0.5 px-2 py-1.5 text-sm border border-gray-300 rounded-lg">
            <option value="utilisateur">Utilisateur</option>
            <option value="admin">Administrateur</option>
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-600">
          Portée
          <select value={form.portee} onChange={e => setForm({ ...form, portee: e.target.value as NouveauJeton['portee'] })}
            className="mt-0.5 px-2 py-1.5 text-sm border border-gray-300 rounded-lg">
            <option value="lecture">Lecture seule</option>
            <option value="ecriture">Lecture et écriture</option>
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-600">
          Échéance
          <select value={form.expire_jours}
            onChange={e => setForm({ ...form, expire_jours: Number(e.target.value) })}
            className="mt-0.5 px-2 py-1.5 text-sm border border-gray-300 rounded-lg">
            <option value="30">30 jours</option>
            <option value="90">90 jours</option>
            <option value="365">1 an</option>
            <option value="730">2 ans</option>
          </select>
        </label>
        <button type="submit" disabled={enCours || !form.nom.trim()}
          className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50">
          <Plus size={14} /> Créer le jeton
        </button>
        <button type="button" onClick={() => void charger()}
          className="ml-auto inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-gray-300 rounded-lg hover:bg-gray-50">
          <RefreshCw size={13} /> Actualiser
        </button>
      </form>

      {erreur && <p role="alert" className="text-sm text-red-700">{erreur}</p>}
      {!jetons && !erreur && <LoadingSpinner label="Chargement…" />}
      {jetons && jetons.length === 0 && <p className="text-sm text-gray-500">Aucun jeton pour l'instant.</p>}
      {jetons && jetons.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-gray-500 border-b border-gray-200">
              <tr>
                <th scope="col" className="py-2 pr-3">Nom</th><th scope="col" className="pr-3">Rôle · portée</th>
                <th scope="col" className="pr-3">Créé</th><th scope="col" className="pr-3">Dernière utilisation</th>
                <th scope="col" className="pr-3">Échéance</th><th scope="col" className="pr-3">État</th>
                <th scope="col" className="text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {jetons.map(j => (
                <tr key={j.id} className={`border-b border-gray-100 align-top ${j.actif ? '' : 'text-gray-400'}`}>
                  <td className="py-2 pr-3">
                    <div className="font-medium">{j.nom}</div>
                    {j.createur && <div className="text-xs text-gray-400">par {j.createur}</div>}
                  </td>
                  <td className="pr-3 text-xs">
                    {j.role === 'admin' ? 'Administrateur' : 'Utilisateur'} · {j.portee === 'ecriture' ? 'écriture' : 'lecture seule'}
                  </td>
                  <td className="pr-3 text-xs">{date(j.cree)}</td>
                  <td className="pr-3 text-xs">{j.derniere_utilisation ? date(j.derniere_utilisation) : 'jamais'}</td>
                  <td className="pr-3 text-xs">{j.expire ? date(j.expire) : 'aucune'}</td>
                  <td className="pr-3">
                    {j.revoque
                      ? <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700" title={j.revoque_par ? `par ${j.revoque_par}` : undefined}>Révoqué</span>
                      : j.actif
                        ? <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">Actif</span>
                        : <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">Expiré</span>}
                  </td>
                  <td className="text-right whitespace-nowrap space-x-1.5">
                    {!j.revoque && (aRevoquer === j.id ? (
                      <>
                        <button type="button" disabled={enCours} onClick={() => void revoquer(j)}
                          className="px-2 py-1 text-xs text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-60">
                          Confirmer (définitif)
                        </button>
                        <button type="button" disabled={enCours} onClick={() => setARevoquer(null)}
                          className="px-2 py-1 text-xs border border-gray-300 rounded-lg hover:bg-gray-50">Annuler</button>
                      </>
                    ) : (
                      <button type="button" onClick={() => setARevoquer(j.id)}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs border border-red-300 text-red-700 rounded-lg hover:bg-red-50">
                        <XCircle size={12} /> Révoquer
                      </button>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
