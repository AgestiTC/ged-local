/**
 * Rangement › Postes — les PC qui envoient leur inventaire (agent Go) ou dont on importe un export
 * WizTree. Le jeton d'un poste n'est montré QU'UNE FOIS : copie par `copierTexte()` (la page doit
 * marcher aussi par la route HTTP du LAN, sans presse-papiers moderne). Doc : docs/agent-de-poste.md.
 */
import { useEffect, useState } from 'react'
import { Copy, KeyRound, Laptop, Loader2, Plus, Power, Upload, FolderPlus } from 'lucide-react'
import { clsx } from 'clsx'
import { extractApiError } from '../../api'
import { inventaireApi, type PosteInventaire } from '../../api/inventaire'
import { useToast } from '../common/Toast'
import { confirmerTexte } from '../common/Confirmation'
import { copierTexte } from '../../utils/clipboard'
import { ilYa } from '../../utils/formatInventaire'

function messageRefus(err: unknown, defaut: string): string {
  const detail = (err as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail
  return detail?.message ?? extractApiError(err, defaut)
}

export default function PostesInventaire() {
  const toast = useToast()
  const [postes, setPostes] = useState<PosteInventaire[] | null>(null)
  const [nomPoste, setNomPoste] = useState('')
  const [jeton, setJeton] = useState<{ poste: string; valeur: string } | null>(null)
  const [dossier, setDossier] = useState<{ posteId: number; libelle: string; racine: string } | null>(null)
  const [wiz, setWiz] = useState({ nom_pc: '', libelle: '', chemin: '/mnt/media/' })

  const charger = async () => {
    try { setPostes(await inventaireApi.postes()) }
    catch (err) { toast.error(extractApiError(err, 'Lecture des postes impossible')) }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void charger() }, [])

  const creer = async () => {
    try {
      const p = await inventaireApi.creerPoste(nomPoste.trim())
      setJeton({ poste: p.nom, valeur: p.jeton_clair }); setNomPoste('')
      await charger()
    } catch (err) { toast.error(messageRefus(err, 'Création refusée')) }
  }

  const renouveler = async (p: PosteInventaire) => {
    if (!(await confirmerTexte(`Nouveau jeton pour « ${p.nom} » ? L'ancien cessera aussitôt de fonctionner : il faudra le remplacer sur le PC.`, 'Nouveau jeton'))) return
    try {
      const r = await inventaireApi.nouveauJeton(p.id)
      setJeton({ poste: p.nom, valeur: r.jeton_clair }); await charger()
    } catch (err) { toast.error(messageRefus(err, 'Renouvellement impossible')) }
  }

  const basculer = async (p: PosteInventaire) => {
    if (p.actif && !(await confirmerTexte(`Désactiver « ${p.nom} » ? Son agent sera refusé jusqu'à sa réactivation.`, 'Désactiver'))) return
    try { await inventaireApi.activerPoste(p.id, !p.actif); await charger() }
    catch (err) { toast.error(messageRefus(err, 'Modification impossible')) }
  }

  const confier = async () => {
    if (!dossier) return
    try {
      await inventaireApi.confierDossier(dossier.posteId, dossier.libelle.trim(), dossier.racine.trim())
      toast.success("Dossier confié : l'inventaire arrive au prochain contact de l'agent (15 min au plus).")
      setDossier(null); await charger()
    } catch (err) { toast.error(messageRefus(err, 'Dossier refusé')) }
  }

  const importer = async () => {
    try {
      await inventaireApi.importerWizTree(wiz.nom_pc.trim(), wiz.libelle.trim(), wiz.chemin.trim())
      toast.success("Import lancé — il se suit dans « Tâches » ; un fichier refusé y est expliqué.")
      setWiz({ nom_pc: '', libelle: '', chemin: '/mnt/media/' })
    } catch (err) { toast.error(messageRefus(err, 'Import refusé')) }
  }

  const copier = async () => {
    if (jeton && (await copierTexte(jeton.valeur))) toast.success('Jeton copié — range-le dans Bitwarden.')
    else toast.error('Copie impossible : sélectionne le jeton et copie-le à la main.')
  }

  if (postes === null) return <div className="text-center py-16"><Loader2 size={28} className="animate-spin mx-auto text-gray-400" /></div>

  const serveur = typeof window !== 'undefined' ? window.location.origin : ''
  return (
    <div className="space-y-6">
      {jeton && (
        <div role="alert" className="border-2 border-amber-400 bg-amber-50 rounded-lg p-4 space-y-2">
          <p className="text-sm font-semibold text-amber-900 flex items-center gap-2"><KeyRound size={16} /> Jeton de « {jeton.poste} » — affiché une seule fois</p>
          <code className="block text-xs break-all bg-white border border-amber-200 rounded p-2 select-all">{jeton.valeur}</code>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void copier()}
              className="flex items-center gap-1 text-sm px-3 py-1.5 bg-amber-600 text-white rounded hover:bg-amber-700"><Copy size={14} /> Copier</button>
            <button type="button" onClick={() => setJeton(null)}
              className="text-sm px-3 py-1.5 border border-amber-300 rounded hover:bg-amber-100">Je l'ai rangé</button>
          </div>
          <p className="text-xs text-amber-900">
            Sur le PC, PowerShell administrateur : <code className="break-all">.\installer-agent.ps1 -Serveur {serveur} -Jeton {'<jeton>'} -Racines "C:\Users"</code>
          </p>
        </div>
      )}

      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-sm font-semibold text-gray-700">Postes</h2>
          <form className="flex gap-2" onSubmit={e => { e.preventDefault(); void creer() }}>
            <input value={nomPoste} onChange={e => setNomPoste(e.target.value)} placeholder="Nom du PC (ex. PC-GAME)"
              required maxLength={60} aria-label="Nom du nouveau poste"
              className="px-2 py-1.5 text-sm border border-gray-300 rounded w-48" />
            <button type="submit" className="flex items-center gap-1 text-sm px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700">
              <Plus size={14} /> Ajouter un poste</button>
          </form>
        </div>
        {postes.length === 0 && <p className="text-sm text-gray-500">Aucun poste. Ajoute un PC pour recevoir son jeton, puis installe l'agent dessus.</p>}
        <ul className="grid gap-3 md:grid-cols-2">
          {postes.map(p => (
            <li key={p.id} className={clsx('border border-gray-200 rounded-lg p-3 space-y-2 min-w-0', !p.actif && 'opacity-60')}>
              <div className="flex items-center gap-2 min-w-0">
                <Laptop size={16} className="text-gray-500 shrink-0" />
                <span className="font-medium truncate">{p.nom}</span>
                {!p.actif && <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-600">désactivé</span>}
              </div>
              <p className="text-xs text-gray-500">
                {p.dernier_contact ? <>Dernier contact {ilYa(p.dernier_contact)}{p.version ? ` · agent ${p.version}` : ''}</>
                  : p.jeton ? 'Agent jamais connecté' : 'Sans agent (import WizTree)'}
              </p>
              {p.emplacements.length > 0 && (
                <ul className="text-xs space-y-0.5">
                  {p.emplacements.map(e => (
                    <li key={e.id} className="truncate" title={e.racine}>
                      <span className="text-gray-500">{e.source === 'agent' ? 'Agent' : 'Import'} :</span> {e.libelle} — <span className="font-mono">{e.racine}</span>
                    </li>
                  ))}
                </ul>
              )}
              {dossier?.posteId === p.id ? (
                <form className="space-y-2 bg-gray-50 rounded p-2" onSubmit={e => { e.preventDefault(); void confier() }}>
                  <input value={dossier.libelle} onChange={e => setDossier({ ...dossier, libelle: e.target.value })} placeholder="Libellé (ex. Documents)"
                    required maxLength={100} aria-label="Libellé du dossier" className="w-full px-2 py-1 text-sm border border-gray-300 rounded" />
                  <input value={dossier.racine} onChange={e => setDossier({ ...dossier, racine: e.target.value })} placeholder="C:\Users\Thomas"
                    required aria-label="Dossier du PC" className="w-full px-2 py-1 text-sm font-mono border border-gray-300 rounded" />
                  <div className="flex gap-2">
                    <button type="submit" className="text-xs px-2 py-1 bg-blue-600 text-white rounded">Confier</button>
                    <button type="button" onClick={() => setDossier(null)} className="text-xs px-2 py-1 border border-gray-300 rounded">Annuler</button>
                  </div>
                </form>
              ) : (
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => setDossier({ posteId: p.id, libelle: '', racine: '' })}
                    className="flex items-center gap-1 text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-50"><FolderPlus size={13} /> Confier un dossier</button>
                  <button type="button" onClick={() => void renouveler(p)}
                    className="flex items-center gap-1 text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-50"><KeyRound size={13} /> Nouveau jeton</button>
                  <button type="button" onClick={() => void basculer(p)}
                    className="flex items-center gap-1 text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-50"><Power size={13} /> {p.actif ? 'Désactiver' : 'Réactiver'}</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="border border-gray-200 rounded-lg p-3 space-y-2">
        <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2"><Upload size={15} /> Importer un export WizTree (PC sans agent)</h2>
        <p className="text-xs text-gray-500">Dépose l'export CSV de WizTree sur le NAS, puis indique son chemin. Une ligne abîmée fait refuser tout l'import : rien n'est alors modifié.</p>
        <form className="grid gap-2 sm:grid-cols-[10rem_12rem_minmax(0,1fr)_auto]" onSubmit={e => { e.preventDefault(); void importer() }}>
          <input value={wiz.nom_pc} onChange={e => setWiz({ ...wiz, nom_pc: e.target.value })} placeholder="Nom du PC" required maxLength={60}
            aria-label="Nom du PC" className="px-2 py-1.5 text-sm border border-gray-300 rounded" />
          <input value={wiz.libelle} onChange={e => setWiz({ ...wiz, libelle: e.target.value })} placeholder="Libellé (facultatif)" maxLength={100}
            aria-label="Libellé" className="px-2 py-1.5 text-sm border border-gray-300 rounded" />
          <input value={wiz.chemin} onChange={e => setWiz({ ...wiz, chemin: e.target.value })} required
            aria-label="Chemin de l'export sur le NAS" className="px-2 py-1.5 text-sm font-mono border border-gray-300 rounded min-w-0" />
          <button type="submit" className="text-sm px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700">Importer</button>
        </form>
      </section>
    </div>
  )
}
