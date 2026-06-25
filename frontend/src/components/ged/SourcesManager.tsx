/**
 * SourcesManager — Sources de fichiers (local / SMB) + exploration + indexation
 * Remplace la saisie manuelle de chemin : on déclare un serveur (NAS…), on liste
 * ses partages, on parcourt, et on indexe le dossier choisi. Identifiants chiffrés
 * côté backend (jamais renvoyés au front).
 */
import { useEffect, useState } from 'react'
import {
  Folder, FolderOpen, HardDrive, Plus, RefreshCw, Server, Trash2, Download, ChevronRight, X,
} from 'lucide-react'
import { sourcesApi, type Source, type SourceInput, type BrowseEntry } from '../../api'
import { useToast } from '../common/Toast'

const FORM_VIDE: SourceInput = { libelle: '', type: 'smb', hote: '', identifiant: '', secret: '', chemin_base: '' }

export default function SourcesManager() {
  const toast = useToast()
  const [sources, setSources] = useState<Source[]>([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<SourceInput>(FORM_VIDE)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)

  // Explorateur
  const [explore, setExplore] = useState<Source | null>(null)
  const [shares, setShares] = useState<string[]>([])
  const [partage, setPartage] = useState<string | null>(null)
  const [chemin, setChemin] = useState('/')
  const [entries, setEntries] = useState<BrowseEntry[]>([])
  const [loadingExpl, setLoadingExpl] = useState(false)
  const [indexing, setIndexing] = useState(false)

  const charger = () => sourcesApi.list().then(setSources).catch(() => {})
  useEffect(() => { charger() }, [])

  const tester = async () => {
    setTesting(true)
    try {
      const r = await sourcesApi.test(form)
      r.ok ? toast.success(form.type === 'smb' ? `Connexion OK — ${r.partages?.length ?? 0} partage(s)` : 'Dossier accessible')
           : toast.error(`Échec : ${r.erreur ?? 'inaccessible'}`)
    } catch { toast.error('Test échoué') } finally { setTesting(false) }
  }

  const ajouter = async () => {
    if (!form.libelle.trim()) { toast.error('Donne un libellé'); return }
    setSaving(true)
    try {
      await sourcesApi.create(form)
      toast.success('Source ajoutée')
      setForm(FORM_VIDE); setShowForm(false); charger()
    } catch { toast.error('Création échouée') } finally { setSaving(false) }
  }

  const supprimer = async (id: string) => {
    try { await sourcesApi.remove(id); charger(); if (explore?.id === id) fermerExplorateur() }
    catch { toast.error('Suppression échouée') }
  }

  const ouvrirExplorateur = async (s: Source) => {
    setExplore(s); setShares([]); setPartage(null); setChemin('/'); setEntries([])
    setLoadingExpl(true)
    try {
      if (s.type === 'smb') {
        setShares(await sourcesApi.shares(s.id))
      } else {
        setEntries(await sourcesApi.browse(s.id, '/'))
      }
    } catch (e) { toast.error('Exploration impossible') } finally { setLoadingExpl(false) }
  }

  const fermerExplorateur = () => { setExplore(null); setShares([]); setPartage(null); setChemin('/'); setEntries([]) }

  const naviguer = async (nouveauChemin: string, sharePick?: string) => {
    if (!explore) return
    setLoadingExpl(true)
    try {
      const p = sharePick ?? partage ?? undefined
      setEntries(await sourcesApi.browse(explore.id, nouveauChemin, p ?? undefined))
      setChemin(nouveauChemin)
      if (sharePick) setPartage(sharePick)
    } catch { toast.error('Dossier illisible') } finally { setLoadingExpl(false) }
  }

  const indexer = async () => {
    if (!explore) return
    setIndexing(true)
    try {
      await sourcesApi.index(explore.id, chemin, partage ?? undefined)
      toast.success('Indexation lancée — suis la progression dans la GED')
    } catch { toast.error('Indexation impossible') } finally { setIndexing(false) }
  }

  return (
    <div className="space-y-3">
      {/* Liste des sources */}
      <div className="space-y-2">
        {sources.map(s => (
          <div key={s.id} className="flex items-center gap-2 border border-gray-200 rounded-lg p-2.5">
            {s.type === 'smb' ? <Server size={16} className="text-blue-600 shrink-0" /> : <HardDrive size={16} className="text-gray-500 shrink-0" />}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium truncate">{s.libelle}</p>
              <p className="text-xs text-gray-400 truncate">
                {s.type === 'smb' ? `\\\\${s.hote}${s.identifiant ? ` (${s.identifiant})` : ' (invité)'}` : s.chemin_base}
              </p>
            </div>
            <button type="button" onClick={() => ouvrirExplorateur(s)} className="text-xs px-2 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 shrink-0">Explorer</button>
            <button type="button" onClick={() => supprimer(s.id)} title="Supprimer" className="p-1 text-gray-400 hover:text-red-500 shrink-0"><Trash2 size={15} /></button>
          </div>
        ))}
        {sources.length === 0 && <p className="text-xs text-gray-400 py-2">Aucune source. Ajoute ton NAS pour indexer ses partages.</p>}
      </div>

      {/* Bouton + formulaire d'ajout */}
      {!showForm ? (
        <button type="button" onClick={() => setShowForm(true)} className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg border border-dashed border-gray-300 text-gray-600 hover:bg-gray-50 w-full justify-center">
          <Plus size={15} /> Ajouter une source
        </button>
      ) : (
        <div className="border border-gray-200 rounded-lg p-3 space-y-2 bg-gray-50">
          <div className="flex gap-2">
            {(['smb', 'local'] as const).map(t => (
              <button key={t} type="button" onClick={() => setForm(f => ({ ...f, type: t }))}
                className={`flex-1 text-sm py-1.5 rounded-md border ${form.type === t ? 'bg-blue-600 text-white border-blue-600' : 'border-gray-200 text-gray-600'}`}>
                {t === 'smb' ? 'Serveur réseau (SMB)' : 'Dossier local (monté)'}
              </button>
            ))}
          </div>
          <input type="text" placeholder="Libellé (ex: NAS-MATO)" value={form.libelle}
            onChange={e => setForm(f => ({ ...f, libelle: e.target.value }))}
            className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5" />
          {form.type === 'smb' ? (
            <>
              <input type="text" placeholder="Hôte / IP (ex: 192.168.42.200)" value={form.hote ?? ''}
                onChange={e => setForm(f => ({ ...f, hote: e.target.value }))}
                className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono" />
              <div className="flex gap-2">
                <input type="text" placeholder="Identifiant (vide = invité)" value={form.identifiant ?? ''}
                  onChange={e => setForm(f => ({ ...f, identifiant: e.target.value }))}
                  className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5" />
                <input type="password" placeholder="Mot de passe / token" value={form.secret ?? ''}
                  onChange={e => setForm(f => ({ ...f, secret: e.target.value }))}
                  className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5" />
              </div>
              <p className="text-xs text-gray-400">🔒 Le mot de passe est chiffré en base (jamais renvoyé).</p>
            </>
          ) : (
            <input type="text" placeholder="Chemin dans le conteneur (ex: /app/documents)" value={form.chemin_base ?? ''}
              onChange={e => setForm(f => ({ ...f, chemin_base: e.target.value }))}
              className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono" />
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => { setShowForm(false); setForm(FORM_VIDE) }} className="text-sm px-3 py-1.5 rounded-md border border-gray-200 text-gray-600">Annuler</button>
            <button type="button" onClick={tester} disabled={testing} className="text-sm px-3 py-1.5 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100 disabled:opacity-50">{testing ? 'Test…' : 'Tester'}</button>
            <button type="button" onClick={ajouter} disabled={saving} className="text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">{saving ? '…' : 'Ajouter'}</button>
          </div>
        </div>
      )}

      {/* Explorateur */}
      {explore && (
        <div className="border border-blue-200 rounded-lg p-3 bg-blue-50/40">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium flex items-center gap-1.5"><FolderOpen size={15} className="text-blue-600" /> {explore.libelle}</span>
            <button type="button" onClick={fermerExplorateur} className="p-1 text-gray-400 hover:text-gray-700"><X size={15} /></button>
          </div>

          {/* SMB : choix du partage */}
          {explore.type === 'smb' && !partage && (
            <div className="space-y-1">
              <p className="text-xs text-gray-500 mb-1">Partages disponibles :</p>
              {shares.map(sh => (
                <button key={sh} type="button" onClick={() => naviguer('/', sh)}
                  className="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 rounded-md hover:bg-white border border-transparent hover:border-gray-200">
                  <Server size={14} className="text-blue-600" /> {sh}
                </button>
              ))}
              {shares.length === 0 && !loadingExpl && <p className="text-xs text-gray-400">Aucun partage (ou identifiants requis).</p>}
            </div>
          )}

          {/* Navigation dossiers (local, ou SMB après choix du partage) */}
          {(explore.type === 'local' || partage) && (
            <>
              <div className="flex items-center gap-1 text-xs text-gray-500 mb-2 flex-wrap">
                {partage && <span className="font-mono">{partage}</span>}
                <span className="font-mono">{chemin}</span>
              </div>
              <div className="max-h-56 overflow-auto border border-gray-200 rounded-md bg-white divide-y divide-gray-50">
                {chemin !== '/' && (
                  <button type="button" onClick={() => naviguer(chemin.replace(/\/[^/]+\/?$/, '') || '/')}
                    className="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 hover:bg-gray-50 text-gray-500">
                    <ChevronRight size={13} className="rotate-180" /> ..
                  </button>
                )}
                {entries.filter(e => e.dossier).map(e => (
                  <button key={e.nom} type="button"
                    onClick={() => naviguer(`${chemin.replace(/\/$/, '')}/${e.nom}`)}
                    className="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 hover:bg-gray-50">
                    <Folder size={14} className="text-amber-500" /> {e.nom}
                  </button>
                ))}
                {entries.filter(e => !e.dossier).slice(0, 50).map(e => (
                  <div key={e.nom} className="flex items-center gap-2 text-sm px-2 py-1.5 text-gray-400">
                    <span className="w-3.5" /> {e.nom}
                  </div>
                ))}
                {entries.length === 0 && !loadingExpl && <p className="text-xs text-gray-400 px-2 py-2">Dossier vide.</p>}
              </div>
              <div className="flex justify-end mt-2">
                <button type="button" onClick={indexer} disabled={indexing}
                  className="flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                  <Download size={15} /> {indexing ? 'Lancement…' : 'Indexer ce dossier'}
                </button>
              </div>
            </>
          )}

          {loadingExpl && <p className="text-xs text-gray-400 mt-2 flex items-center gap-1"><RefreshCw size={12} className="animate-spin" /> Chargement…</p>}
        </div>
      )}
    </div>
  )
}
