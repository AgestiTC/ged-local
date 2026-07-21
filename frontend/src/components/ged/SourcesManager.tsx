/**
 * SourcesManager — Sources de fichiers (local / SMB) + exploration + indexation
 * Remplace la saisie manuelle de chemin : on déclare un serveur (NAS…), on liste
 * ses partages, on parcourt, et on indexe le dossier choisi. Identifiants chiffrés
 * côté backend (jamais renvoyés au front).
 */
import { useEffect, useState } from 'react'
import {
  AlertTriangle, Folder, FolderOpen, HardDrive, Plus, RefreshCw, Server, Trash2, Download, ChevronRight, X, Pencil,
} from 'lucide-react'
import { sourcesApi, suivreJob, extractApiError, type Source, type SourceInput, type BrowseEntry } from '../../api'
import { useToast } from '../common/Toast'
import IndexedFolders from './IndexedFolders'

const FORM_VIDE: SourceInput = { libelle: '', type: 'smb', hote: '', identifiant: '', secret: '', chemin_base: '' }

export default function SourcesManager() {
  const toast = useToast()
  const [sources, setSources] = useState<Source[]>([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<SourceInput>(FORM_VIDE)
  const [editId, setEditId] = useState<string | null>(null)   // null = création ; sinon édition
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)

  // Explorateur
  const [indexedSrc, setIndexedSrc] = useState<Source | null>(null)
  const [explore, setExplore] = useState<Source | null>(null)
  const [shares, setShares] = useState<string[]>([])
  const [sharesSel, setSharesSel] = useState<Set<string>>(new Set())   // partages cochés à indexer en entier
  const [errExpl, setErrExpl] = useState<string | null>(null)   // cause d'échec de l'exploration
  const [partage, setPartage] = useState<string | null>(null)
  const [chemin, setChemin] = useState('/')
  const [entries, setEntries] = useState<BrowseEntry[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())   // dossiers cochés à indexer
  const [loadingExpl, setLoadingExpl] = useState(false)
  const [indexing, setIndexing] = useState(false)
  const [reindexing, setReindexing] = useState<string | null>(null)   // id de la source en ré-indexation
  const [syncing, setSyncing] = useState<string | null>(null)         // id de la source en synchro
  const [recap, setRecap] = useState<Record<string, string>>({})      // récap du dernier diff, par source

  const joinPath = (base: string, nom: string) => `${base.replace(/\/$/, '')}/${nom}`
  // « Tout cocher » d'une vue — sur ACTION explicite uniquement. NE PLUS cocher automatiquement à
  // la navigation : le pré-cochage indexait tout un partage alors qu'on ne voulait qu'un dossier.
  const cocherTout = (base: string, items: BrowseEntry[]) =>
    setSelected(new Set(items.filter(e => e.dossier).map(e => joinPath(base, e.nom))))

  const charger = () => sourcesApi.list().then(setSources).catch(() => {})
  useEffect(() => { charger() }, [])

  const tester = async () => {
    setTesting(true)
    try {
      const r = await sourcesApi.test(form)
      r.ok ? toast.success(form.type === 'smb' ? `Connexion OK — ${r.partages?.length ?? 0} partage(s)` : 'Dossier accessible')
           : toast.error(`Échec : ${r.erreur ?? 'inaccessible'}`)
    } catch (e) { toast.error(extractApiError(e, 'Test échoué')) } finally { setTesting(false) }
  }

  // Ouvre le formulaire en ÉDITION, pré-rempli depuis la source (le secret n'est jamais
  // renvoyé par le backend → champ mot de passe vide = « laisser inchangé »).
  const editer = (s: Source) => {
    fermerExplorateur(); setIndexedSrc(null)
    setEditId(s.id)
    setForm({
      libelle: s.libelle, type: s.type,
      hote: s.hote ?? '', identifiant: s.identifiant ?? '', secret: '',
      chemin_base: s.chemin_base ?? '',
    })
    setShowForm(true)
  }

  const fermerForm = () => { setShowForm(false); setForm(FORM_VIDE); setEditId(null) }

  const enregistrer = async () => {
    if (!form.libelle.trim()) { toast.error('Donne un libellé'); return }
    setSaving(true)
    try {
      if (editId) {
        await sourcesApi.update(editId, form)
        toast.success('Source modifiée')
      } else {
        await sourcesApi.create(form)
        toast.success('Source ajoutée')
      }
      fermerForm(); charger()
    } catch (e) { toast.error(extractApiError(e, editId ? 'Modification échouée' : 'Création échouée')) } finally { setSaving(false) }
  }

  const supprimer = async (id: string) => {
    try { await sourcesApi.remove(id); charger(); if (explore?.id === id) fermerExplorateur() }
    catch (e) { toast.error(extractApiError(e, 'Suppression échouée')) }
  }

  const ouvrirExplorateur = async (s: Source) => {
    setExplore(s); setShares([]); setSharesSel(new Set()); setPartage(null); setChemin('/'); setEntries([]); setErrExpl(null)
    setLoadingExpl(true)
    try {
      if (s.type === 'smb') {
        setShares(await sourcesApi.shares(s.id))
      } else {
        const data = await sourcesApi.browse(s.id, '/')
        setEntries(data)   // rien de coché par défaut : l'utilisateur choisit
      }
    } catch (e) {
      // Le backend explique la cause (ex. secret déchiffrable → « re-saisis le mot de passe »).
      // L'avaler laissait l'utilisateur devant un « Aucun partage » incompréhensible.
      setErrExpl(extractApiError(e, 'Exploration impossible'))
      toast.error(extractApiError(e, 'Exploration impossible'))
    } finally { setLoadingExpl(false) }
  }

  const fermerExplorateur = () => { setExplore(null); setShares([]); setPartage(null); setChemin('/'); setEntries([]); setErrExpl(null) }

  const naviguer = async (nouveauChemin: string, sharePick?: string) => {
    if (!explore) return
    setLoadingExpl(true)
    try {
      const p = sharePick ?? partage ?? undefined
      const data = await sourcesApi.browse(explore.id, nouveauChemin, p ?? undefined)
      setEntries(data)   // ne PAS cocher automatiquement en entrant dans un dossier
      setChemin(nouveauChemin)
      if (sharePick) setPartage(sharePick)
    } catch (e) { toast.error(extractApiError(e, 'Dossier illisible')) } finally { setLoadingExpl(false) }
  }

  const toggleSel = (path: string) => setSelected(prev => {
    const n = new Set(prev); n.has(path) ? n.delete(path) : n.add(path); return n
  })
  const toggleShareSel = (sh: string) => setSharesSel(prev => {
    const n = new Set(prev); n.has(sh) ? n.delete(sh) : n.add(sh); return n
  })

  // Indexe EN ENTIER chaque partage coché (récursif). L'affinage se fait ensuite via « Indexés → Gérer »
  // (retrait des sous-dossiers non voulus). Sélection grossière ici, précision au retrait.
  const indexerPartages = async () => {
    if (!explore || sharesSel.size === 0) return
    setIndexing(true)
    try {
      for (const sh of sharesSel) await sourcesApi.index(explore.id, '/', sh)
      toast.success(`Indexation lancée — ${sharesSel.size} partage(s) entier(s)`)
      setSharesSel(new Set())
    } catch (e) { toast.error(extractApiError(e, 'Indexation impossible')) } finally { setIndexing(false) }
  }

  const indexer = async () => {
    if (!explore) return
    // Dossiers cochés de la vue courante ; sinon le dossier courant lui-même
    const dansLaVue = entries.filter(e => e.dossier).map(e => joinPath(chemin, e.nom))
    const cibles = dansLaVue.filter(p => selected.has(p))
    const aIndexer = cibles.length > 0 ? cibles : [chemin]
    setIndexing(true)
    try {
      for (const c of aIndexer) await sourcesApi.index(explore.id, c, partage ?? undefined)
      toast.success(`Indexation lancée — ${aIndexer.length} dossier(s)`)
    } catch (e) { toast.error(extractApiError(e, 'Indexation impossible')) } finally { setIndexing(false) }
  }

  // Re-scanne d'un clic tous les dossiers déjà indexés de la source (rattrape les nouveautés).
  const reindexer = async (s: Source) => {
    setReindexing(s.id)
    try {
      const r = await sourcesApi.reindex(s.id)
      toast.success(r.message)
    } catch (e) { toast.error(extractApiError(e, 'Ré-indexation impossible')) } finally { setReindexing(null) }
  }

  // Synchro incrémentale : lance un job par dossier indexé, puis agrège leurs résultats pour
  // afficher ce qui a RÉELLEMENT changé (une synchro à vide doit se voir comme telle).
  const synchroniser = async (s: Source) => {
    setSyncing(s.id)
    setRecap(r => ({ ...r, [s.id]: 'Comparaison en cours…' }))
    try {
      const { job_ids, nb, message } = await sourcesApi.sync(s.id)
      if (!job_ids.length) { toast.info(message); setRecap(r => ({ ...r, [s.id]: message })); return }
      toast.success(`Synchronisation lancée — ${nb} dossier(s) comparés`)

      const total = { nouveaux: 0, modifies: 0, absents: 0, deplaces: 0, revenus: 0, inchanges: 0 }
      const echecs: string[] = []
      await Promise.all(job_ids.map(async id => {
        try {
          const job = await suivreJob(id)
          if (job.statut === 'failed') { echecs.push(job.erreur || 'échec'); return }
          const r = (job.resultat || {}) as Partial<typeof total>
          for (const k of Object.keys(total) as (keyof typeof total)[]) total[k] += r[k] ?? 0
        } catch { echecs.push('job introuvable') }
      }))

      const parts = [
        total.nouveaux && `+${total.nouveaux} nouveau(x)`,
        total.modifies && `~${total.modifies} modifié(s)`,
        total.deplaces && `↔${total.deplaces} déplacé(s)`,
        total.revenus && `⟲${total.revenus} revenu(s)`,
        total.absents && `−${total.absents} absent(s)`,
      ].filter(Boolean) as string[]
      const texte = parts.length
        ? `${parts.join(' · ')} — ${total.inchanges} inchangé(s)`
        : `Aucun écart — ${total.inchanges} fichier(s) déjà à jour`
      setRecap(r => ({ ...r, [s.id]: echecs.length ? `${texte} · ⚠ ${echecs[0]}` : texte }))
      if (echecs.length) toast.error(echecs[0])
    } catch (e) {
      const msg = extractApiError(e, 'Synchronisation impossible')
      setRecap(r => ({ ...r, [s.id]: `⚠ ${msg}` }))
      toast.error(msg)
    } finally { setSyncing(null) }
  }

  return (
    <div className="space-y-3">
      {/* Liste des sources */}
      <div className="space-y-2">
        {sources.map(s => (
          <div key={s.id} className="border border-gray-200 rounded-lg p-2.5">
            <div className="flex items-center gap-2">
              {s.type === 'smb' ? <Server size={16} className="text-blue-600 shrink-0" /> : <HardDrive size={16} className="text-gray-500 shrink-0" />}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">{s.libelle}</p>
                <p className="text-xs text-gray-400 truncate">
                  {s.type === 'smb' ? `\\\\${s.hote}${s.identifiant ? ` (${s.identifiant})` : ' (invité)'}` : s.chemin_base}
                </p>
              </div>
              <button type="button" onClick={() => { setIndexedSrc(null); ouvrirExplorateur(s) }} className="text-xs px-2 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 shrink-0">Explorer</button>
              <button type="button" onClick={() => { fermerExplorateur(); setIndexedSrc(s) }} className="text-xs px-2 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 shrink-0">Indexés</button>
              {/* Action principale : ne traite QUE les écarts (rien à faire = quasi gratuit). */}
              <button type="button" onClick={() => synchroniser(s)} disabled={syncing === s.id}
                title="Comparer la source à l'index et ne traiter que les écarts : fichiers ajoutés, modifiés, déplacés ou disparus. Sans changement, rien n'est téléchargé."
                className="text-xs px-2 py-1 rounded-md border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 disabled:opacity-50 shrink-0 flex items-center gap-1">
                <RefreshCw size={12} className={syncing === s.id ? 'animate-spin' : ''} /> {syncing === s.id ? '…' : 'Synchroniser'}
              </button>
              {/* Secours : re-scan complet, utile si l'index a dérivé ou après un incident. */}
              <button type="button" onClick={() => reindexer(s)} disabled={reindexing === s.id}
                title="Re-scan COMPLET des dossiers déjà indexés (plus lent : relit tous les fichiers). À réserver aux cas où l'index a dérivé — sinon préfère « Synchroniser »."
                className="text-xs px-2 py-1 rounded-md text-gray-500 hover:bg-gray-50 disabled:opacity-50 shrink-0">
                {reindexing === s.id ? '…' : 'Réindexer'}
              </button>
              <button type="button" onClick={() => editer(s)} title="Modifier / renommer" className="p-1 text-gray-400 hover:text-blue-600 shrink-0"><Pencil size={15} /></button>
              <button type="button" onClick={() => supprimer(s.id)} title="Supprimer" className="p-1 text-gray-400 hover:text-red-500 shrink-0"><Trash2 size={15} /></button>
            </div>
            {recap[s.id] && (
              <p className={`text-xs mt-1.5 pl-6 ${recap[s.id].startsWith('⚠') ? 'text-red-600' : 'text-gray-500'}`}>
                {recap[s.id]}
              </p>
            )}
          </div>
        ))}
        {sources.length === 0 && <p className="text-xs text-gray-400 py-2">Aucune source. Ajoute ton NAS pour indexer ses partages.</p>}
      </div>

      {/* Panneau « dossiers indexés » de la source sélectionnée */}
      {indexedSrc && <IndexedFolders source={indexedSrc} onClose={() => setIndexedSrc(null)} />}

      {/* Bouton + formulaire d'ajout */}
      {!showForm ? (
        <button type="button" onClick={() => { setEditId(null); setForm(FORM_VIDE); setShowForm(true) }} className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg border border-dashed border-gray-300 text-gray-600 hover:bg-gray-50 w-full justify-center">
          <Plus size={15} /> Ajouter une source
        </button>
      ) : (
        <div className="border border-gray-200 rounded-lg p-3 space-y-2 bg-gray-50">
          <p className="text-sm font-medium text-gray-700">{editId ? 'Modifier la source' : 'Nouvelle source'}</p>
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
                <input type="password" placeholder={editId ? 'Mot de passe (vide = inchangé)' : 'Mot de passe / token'} value={form.secret ?? ''}
                  onChange={e => setForm(f => ({ ...f, secret: e.target.value }))}
                  className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5" />
              </div>
              <p className="text-xs text-gray-400">🔒 Le mot de passe est chiffré en base (jamais renvoyé).
                {editId && ' Laisse le champ vide pour le conserver, ou re-saisis-le si l\'exploration échoue.'}</p>
            </>
          ) : (
            <input type="text" placeholder="Chemin dans le conteneur (ex: /app/documents)" value={form.chemin_base ?? ''}
              onChange={e => setForm(f => ({ ...f, chemin_base: e.target.value }))}
              className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono" />
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={fermerForm} className="text-sm px-3 py-1.5 rounded-md border border-gray-200 text-gray-600">Annuler</button>
            <button type="button" onClick={tester} disabled={testing} className="text-sm px-3 py-1.5 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100 disabled:opacity-50">{testing ? 'Test…' : 'Tester'}</button>
            <button type="button" onClick={enregistrer} disabled={saving} className="text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">{saving ? '…' : (editId ? 'Enregistrer' : 'Ajouter')}</button>
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

          {/* Cause d'échec renvoyée par le backend (au lieu d'un « Aucun partage » muet) */}
          {errExpl && (
            <div className="flex items-start gap-2 text-xs bg-red-50 border border-red-200 text-red-700 rounded-md px-3 py-2 mb-2">
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <div className="flex-1">
                <p>{errExpl}</p>
                <button type="button" onClick={() => { const s = explore; fermerExplorateur(); editer(s) }}
                  className="mt-1 underline hover:no-underline">Modifier la source (re-saisir le mot de passe)</button>
              </div>
            </div>
          )}

          {/* SMB : choix du partage — case pour indexer TOUT le partage, ou clic sur le nom pour entrer */}
          {explore.type === 'smb' && !partage && (
            <div className="space-y-1">
              <p className="text-xs text-gray-500 mb-1">
                <strong>Coche</strong> un partage pour l'indexer en entier, ou <strong>clique son nom</strong> pour
                choisir des sous-dossiers. Tu pourras affiner ensuite via « Indexés → Gérer ».
              </p>
              {shares.map(sh => (
                <div key={sh} className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white border border-transparent hover:border-gray-200">
                  <input type="checkbox" checked={sharesSel.has(sh)} onChange={() => toggleShareSel(sh)}
                    className="w-4 h-4 accent-blue-600 shrink-0" aria-label={`Indexer tout le partage ${sh}`} />
                  <button type="button" onClick={() => naviguer('/', sh)}
                    className="flex items-center gap-2 flex-1 text-left text-sm min-w-0">
                    <Server size={14} className="text-blue-600 shrink-0" />
                    <span className="truncate">{sh}</span>
                    <ChevronRight size={12} className="text-gray-300 ml-auto shrink-0" />
                  </button>
                </div>
              ))}
              {shares.length === 0 && !loadingExpl && !errExpl && (
                <p className="text-xs text-gray-400">Aucun partage sur ce serveur.</p>
              )}
              {sharesSel.size > 0 && (
                <div className="flex justify-end pt-1">
                  <button type="button" onClick={indexerPartages} disabled={indexing}
                    className="flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                    <Download size={15} />
                    {indexing ? 'Lancement…' : `Indexer ${sharesSel.size} partage(s) entier(s)`}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Navigation dossiers (local, ou SMB après choix du partage) */}
          {(explore.type === 'local' || partage) && (
            <>
              <div className="flex items-center justify-between text-xs text-gray-500 mb-2 flex-wrap gap-1">
                <span className="font-mono">{partage && `${partage} `}{chemin}</span>
                <span className="flex items-center gap-2">
                  <button type="button" onClick={() => cocherTout(chemin, entries)} className="text-blue-600 hover:underline">Tout cocher</button>
                  <span className="text-gray-300">·</span>
                  <button type="button" onClick={() => setSelected(new Set())} className="text-gray-500 hover:underline">Tout décocher</button>
                </span>
              </div>
              <div className="max-h-56 overflow-auto border border-gray-200 rounded-md bg-white divide-y divide-gray-50">
                {chemin !== '/' && (
                  <button type="button" onClick={() => naviguer(chemin.replace(/\/[^/]+\/?$/, '') || '/')}
                    className="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 hover:bg-gray-50 text-gray-500">
                    <ChevronRight size={13} className="rotate-180" /> ..
                  </button>
                )}
                {entries.filter(e => e.dossier).map(e => {
                  const path = joinPath(chemin, e.nom)
                  return (
                    <div key={e.nom} className="flex items-center gap-2 px-2 py-1.5 hover:bg-gray-50">
                      <input type="checkbox" checked={selected.has(path)} onChange={() => toggleSel(path)}
                        className="w-4 h-4 accent-blue-600 shrink-0" aria-label={`Indexer ${e.nom}`} />
                      <button type="button" onClick={() => naviguer(path)}
                        className="flex items-center gap-2 flex-1 text-left text-sm min-w-0">
                        <Folder size={14} className="text-amber-500 shrink-0" />
                        <span className="truncate">{e.nom}</span>
                        <ChevronRight size={12} className="text-gray-300 ml-auto shrink-0" />
                      </button>
                    </div>
                  )
                })}
                {entries.filter(e => !e.dossier).slice(0, 50).map(e => (
                  <div key={e.nom} className="flex items-center gap-2 text-sm px-2 py-1.5 text-gray-400">
                    <span className="w-4 shrink-0" /> {e.nom}
                  </div>
                ))}
                {entries.length === 0 && !loadingExpl && <p className="text-xs text-gray-400 px-2 py-2">Dossier vide.</p>}
              </div>
              {(() => {
                const nbSel = entries.filter(e => e.dossier && selected.has(joinPath(chemin, e.nom))).length
                return (
                  <div className="flex justify-end mt-2">
                    <button type="button" onClick={indexer} disabled={indexing}
                      className="flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                      <Download size={15} />
                      {indexing ? 'Lancement…' : (nbSel > 0 ? `Indexer la sélection (${nbSel})` : 'Indexer ce dossier')}
                    </button>
                  </div>
                )
              })()}
            </>
          )}

          {loadingExpl && <p className="text-xs text-gray-400 mt-2 flex items-center gap-1"><RefreshCw size={12} className="animate-spin" /> Chargement…</p>}
        </div>
      )}
    </div>
  )
}
