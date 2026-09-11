/**
 * ScannersManager — Paramètres › Scanners & profils de scan
 * ==========================================================
 * Trois blocs :
 *  - la BOÎTE À SCANS : le dossier (déjà indexé par une source) où les scanners déposent
 *    leurs PDF quand on scanne depuis l'appareil (bouton Start du Brother, IJ Scan Utility…) ;
 *  - les SCANNERS eSCL : une adresse IP, un test qui lit les capacités (vitre, chargeur,
 *    recto-verso, résolutions). Pas de découverte automatique (mDNS ne traverse pas Docker) ;
 *  - les PROFILS : où ranger, quels tags, quel nom, avec quels réglages — et qui décide
 *    (« fixe » : rangé dès l'indexation ; « l'IA propose » : confirmé dans la page Scans).
 */
import { useEffect, useState } from 'react'
import { Check, ChevronRight, Loader2, Pencil, Plus, RefreshCw, ScanLine, Trash2, X } from 'lucide-react'
import { scanApi, sourcesApi, extractApiError, type Scanner, type ScanProfil, type ScanProfilInput, type Source } from '../../api'
import { useToast } from '../common/Toast'

const PROFIL_VIDE: ScanProfilInput = {
  nom: '', icone: '', destination: '', tags: [], mots_cles: [], modele_nom: '{date}_{profil}',
  reglages: { source: 'vitre', couleur: 'couleur', dpi: 300, recto_verso: false },
  scanner_id: null, classement: 'fixe', position: 0, actif: true,
}

const csv = (l: string[]) => l.join(', ')
const parseCsv = (s: string) => s.split(',').map(t => t.trim()).filter(Boolean)

function decrireCapacites(c: Scanner['capacites']): string {
  if (!c) return 'non testé'
  const parts = [
    c.vitre && 'vitre', c.chargeur && (c.recto_verso ? 'chargeur recto-verso' : 'chargeur'),
    c.resolutions.length && `${c.resolutions.join('/')} dpi`,
  ].filter(Boolean)
  return `${c.modele || 'modèle inconnu'} — ${parts.join(' · ') || 'capacités vides'}`
}

export default function ScannersManager() {
  const toast = useToast()
  const [boite, setBoite] = useState('')
  const [boiteSaving, setBoiteSaving] = useState(false)
  const [sources, setSources] = useState<Source[]>([])
  const [scanners, setScanners] = useState<Scanner[]>([])
  const [profils, setProfils] = useState<ScanProfil[]>([])
  const [testing, setTesting] = useState<string | null>(null)

  // Formulaire scanner (création ou édition)
  const [scForm, setScForm] = useState<{ id?: string; nom: string; url: string } | null>(null)
  // Formulaire profil
  const [prForm, setPrForm] = useState<{ id?: string } & ScanProfilInput | null>(null)
  const [saving, setSaving] = useState(false)

  const charger = () => {
    scanApi.config().then(c => setBoite(c.boite_chemin)).catch(() => {})
    scanApi.scanners().then(setScanners).catch(() => {})
    scanApi.profils().then(setProfils).catch(() => {})
    sourcesApi.list().then(l => setSources(l.filter(s => s.type === 'smb' || s.type === 'local'))).catch(() => {})
  }
  useEffect(() => { charger() }, [])

  const sauverBoite = async () => {
    setBoiteSaving(true)
    try {
      const r = await scanApi.setConfig(boite)
      setBoite(r.boite_chemin)
      toast.success(r.boite_chemin ? 'Boîte à scans enregistrée' : 'Boîte à scans désactivée')
    } catch (e) { toast.error(extractApiError(e, 'Enregistrement impossible')) } finally { setBoiteSaving(false) }
  }

  const sauverScanner = async () => {
    if (!scForm) return
    setSaving(true)
    try {
      if (scForm.id) await scanApi.modifierScanner(scForm.id, { nom: scForm.nom, url: scForm.url })
      else await scanApi.creerScanner({ nom: scForm.nom, url: scForm.url })
      setScForm(null); charger()
      toast.success('Scanner enregistré — lance « Tester » pour lire ses capacités')
    } catch (e) { toast.error(extractApiError(e, 'Enregistrement impossible')) } finally { setSaving(false) }
  }

  const tester = async (s: Scanner) => {
    setTesting(s.id)
    try {
      const r = await scanApi.testerScanner(s.id)
      if (r.ok) toast.success(`${r.capacites?.modele || s.nom} répond — ${r.statut?.etat}`)
      else toast.error(`Échec : ${r.erreur}`)
      charger()
    } catch (e) { toast.error(extractApiError(e, 'Test impossible')) } finally { setTesting(null) }
  }

  const supprimerScanner = async (s: Scanner) => {
    if (!window.confirm(`Retirer le scanner « ${s.nom} » ?`)) return
    try { await scanApi.supprimerScanner(s.id); charger() } catch (e) { toast.error(extractApiError(e)) }
  }

  const sauverProfil = async () => {
    if (!prForm) return
    setSaving(true)
    const { id, ...body } = prForm
    try {
      if (id) await scanApi.modifierProfil(id, body)
      else await scanApi.creerProfil(body)
      setPrForm(null); charger(); toast.success('Profil enregistré')
    } catch (e) { toast.error(extractApiError(e, 'Enregistrement impossible')) } finally { setSaving(false) }
  }

  const supprimerProfil = async (p: ScanProfil) => {
    if (!window.confirm(`Supprimer le profil « ${p.nom} » ? (les documents déjà rangés ne bougent pas)`)) return
    try { await scanApi.supprimerProfil(p.id); charger() } catch (e) { toast.error(extractApiError(e)) }
  }

  const hotesSmb = sources.filter(s => s.type === 'smb' && s.hote).map(s => `smb://${s.hote}/${(s.chemin_base || 'Partage').replace(/^\/+/, '')}`)
  const input = 'w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md bg-white'
  const label = 'block text-xs font-medium text-gray-600 mb-0.5'

  return (
    <div className="space-y-6">
      {/* ── Boîte à scans ─────────────────────────────────── */}
      <section>
        <h3 className="text-sm font-semibold text-gray-800 mb-1">Boîte à scans (dossier de dépôt)</h3>
        <p className="text-xs text-gray-500 mb-2">
          Le dossier où les scanners déposent leurs PDF quand on scanne <em>depuis l'appareil</em> (bouton Start
          du Brother via iPrint&amp;Scan, IJ Scan Utility du Canon). Il doit être couvert par une source indexée
          (synchronisation activée) : tout ce qui y arrive apparaît dans la page <strong>Scans</strong>, prêt à être rangé.
        </p>
        <div className="flex gap-2 items-center">
          <input value={boite} onChange={e => setBoite(e.target.value)} className={input} list="boite-suggestions"
            placeholder="smb://NAS-MATO/Documents/Scans  (vide = seule la capture depuis Matothèque alimente la boîte)" />
          <datalist id="boite-suggestions">{hotesSmb.map(h => <option key={h} value={`${h}/Scans`} />)}</datalist>
          <button type="button" onClick={sauverBoite} disabled={boiteSaving}
            className="px-3 py-1.5 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-60 shrink-0">
            {boiteSaving ? <Loader2 size={14} className="animate-spin" /> : 'Enregistrer'}
          </button>
        </div>
      </section>

      {/* ── Scanners ─────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5"><ScanLine size={14} className="text-teal-600" /> Scanners (eSCL)</h3>
          <button type="button" onClick={() => setScForm({ nom: '', url: '' })}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-gray-300 hover:bg-gray-50">
            <Plus size={13} /> Ajouter
          </button>
        </div>
        <p className="text-xs text-gray-500 mb-2">
          Un multifonction en Wi-Fi (Canon G3570…) ou un scanner USB partagé par NAPS2. Saisis son adresse IP
          (réservation DHCP conseillée), puis <strong>Tester</strong> : Matothèque lit ce qu'il sait faire.
        </p>
        {scForm && (
          <div className="border border-blue-200 bg-blue-50/40 rounded-lg p-3 mb-2 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
            <div><label className={label}>Nom</label><input className={input} value={scForm.nom} onChange={e => setScForm({ ...scForm, nom: e.target.value })} placeholder="Canon du salon" /></div>
            <div><label className={label}>Adresse</label><input className={input} value={scForm.url} onChange={e => setScForm({ ...scForm, url: e.target.value })} placeholder="192.168.42.50 ou http://pc-bureau:9880" /></div>
            <div className="flex items-end gap-1">
              <button type="button" onClick={sauverScanner} disabled={saving || !scForm.nom.trim() || !scForm.url.trim()}
                className="px-3 py-1.5 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-60"><Check size={14} /></button>
              <button type="button" onClick={() => setScForm(null)} className="px-2 py-1.5 text-sm rounded-md border border-gray-300"><X size={14} /></button>
            </div>
          </div>
        )}
        {scanners.length === 0 && !scForm && <p className="text-xs text-gray-400 italic">Aucun scanner déclaré.</p>}
        <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">
          {scanners.map(s => (
            <li key={s.id} className="flex items-center gap-2 px-3 py-2 text-sm">
              <span className={`w-2 h-2 rounded-full shrink-0 ${s.dernier_etat === 'ok' ? 'bg-emerald-500' : s.dernier_etat ? 'bg-red-500' : 'bg-gray-300'}`}
                title={s.dernier_etat || 'non testé'} />
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{s.nom} <span className="text-gray-400 font-normal text-xs">{s.url}</span></div>
                <div className="text-xs text-gray-500 truncate">{decrireCapacites(s.capacites)}{s.dernier_etat && s.dernier_etat !== 'ok' ? ` — ${s.dernier_etat}` : ''}</div>
              </div>
              <button type="button" onClick={() => tester(s)} disabled={testing === s.id} title="Lire les capacités de l'appareil"
                className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-gray-300 hover:bg-gray-50 disabled:opacity-60">
                {testing === s.id ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Tester
              </button>
              <button type="button" onClick={() => setScForm({ id: s.id, nom: s.nom, url: s.url })} className="p-1 text-gray-400 hover:text-blue-600" title="Modifier"><Pencil size={14} /></button>
              <button type="button" onClick={() => supprimerScanner(s)} className="p-1 text-gray-400 hover:text-red-600" title="Retirer"><Trash2 size={14} /></button>
            </li>
          ))}
        </ul>
      </section>

      {/* ── Profils ──────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-gray-800">Profils de scan (où ranger, quels tags)</h3>
          <button type="button" onClick={() => setPrForm({ ...PROFIL_VIDE })}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-gray-300 hover:bg-gray-50">
            <Plus size={13} /> Ajouter
          </button>
        </div>
        <p className="text-xs text-gray-500 mb-2">
          Un profil = une destination (<code>smb://hote/partage/Dossier/{'{annee}'}</code>), des tags, un modèle de
          nom (<code>{'{date}'}</code>, <code>{'{annee}'}</code>, <code>{'{mois}'}</code>, <code>{'{profil}'}</code>, <code>{'{nom}'}</code>)
          et des réglages. Les <em>mots-clés</em> servent à proposer le profil d'après ce que l'IA a lu.
        </p>
        {prForm && (
          <div className="border border-blue-200 bg-blue-50/40 rounded-lg p-3 mb-2 space-y-2">
            <div className="grid gap-2 sm:grid-cols-[auto_1fr_1fr]">
              <div><label className={label}>Icône</label><input className={`${input} w-14 text-center`} value={prForm.icone || ''} onChange={e => setPrForm({ ...prForm, icone: e.target.value })} placeholder="🧾" maxLength={4} /></div>
              <div><label className={label}>Nom</label><input className={input} value={prForm.nom} onChange={e => setPrForm({ ...prForm, nom: e.target.value })} placeholder="Facture" /></div>
              <div><label className={label}>Modèle de nom</label><input className={input} value={prForm.modele_nom || ''} onChange={e => setPrForm({ ...prForm, modele_nom: e.target.value })} placeholder="{date}_{profil}" /></div>
            </div>
            <div>
              <label className={label}>Destination</label>
              <input className={input} list="dest-suggestions" value={prForm.destination} onChange={e => setPrForm({ ...prForm, destination: e.target.value })}
                placeholder="smb://NAS-MATO/Documents/Factures/{annee}" />
              <datalist id="dest-suggestions">{hotesSmb.map(h => <option key={h} value={`${h}/`} />)}</datalist>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <div><label className={label}>Tags (séparés par des virgules)</label><input className={input} value={csv(prForm.tags)} onChange={e => setPrForm({ ...prForm, tags: parseCsv(e.target.value) })} placeholder="facture, scan" /></div>
              <div><label className={label}>Mots-clés de reconnaissance</label><input className={input} value={csv(prForm.mots_cles)} onChange={e => setPrForm({ ...prForm, mots_cles: parseCsv(e.target.value) })} placeholder="facture, montant, TTC" /></div>
            </div>
            <div className="grid gap-2 sm:grid-cols-5">
              <div><label className={label}>Source</label>
                <select className={input} value={prForm.reglages.source || 'vitre'} onChange={e => setPrForm({ ...prForm, reglages: { ...prForm.reglages, source: e.target.value as 'vitre' | 'chargeur' } })}>
                  <option value="vitre">Vitre</option><option value="chargeur">Chargeur</option>
                </select></div>
              <div><label className={label}>Couleur</label>
                <select className={input} value={prForm.reglages.couleur || 'couleur'} onChange={e => setPrForm({ ...prForm, reglages: { ...prForm.reglages, couleur: e.target.value as 'couleur' | 'gris' | 'nb' } })}>
                  <option value="couleur">Couleur</option><option value="gris">Gris</option><option value="nb">Noir et blanc</option>
                </select></div>
              <div><label className={label}>Résolution</label>
                <select className={input} value={prForm.reglages.dpi || 300} onChange={e => setPrForm({ ...prForm, reglages: { ...prForm.reglages, dpi: Number(e.target.value) } })}>
                  {[150, 200, 300, 400, 600].map(d => <option key={d} value={d}>{d} dpi</option>)}
                </select></div>
              <div><label className={label}>Scanner par défaut</label>
                <select className={input} value={prForm.scanner_id || ''} onChange={e => setPrForm({ ...prForm, scanner_id: e.target.value || null })}>
                  <option value="">— au choix —</option>{scanners.map(s => <option key={s.id} value={s.id}>{s.nom}</option>)}
                </select></div>
              <div className="flex items-end pb-1.5">
                <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={!!prForm.reglages.recto_verso} onChange={e => setPrForm({ ...prForm, reglages: { ...prForm.reglages, recto_verso: e.target.checked } })} /> Recto-verso</label>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <label className="flex items-center gap-1.5"><input type="radio" checked={prForm.classement === 'fixe'} onChange={() => setPrForm({ ...prForm, classement: 'fixe' })} /> Rangé aussitôt indexé</label>
              <label className="flex items-center gap-1.5"><input type="radio" checked={prForm.classement === 'ia_confirme'} onChange={() => setPrForm({ ...prForm, classement: 'ia_confirme' })} /> Attend ma confirmation dans la page Scans</label>
              <span className="flex-1" />
              <button type="button" onClick={sauverProfil} disabled={saving || !prForm.nom.trim() || !prForm.destination.trim()}
                className="px-3 py-1.5 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-60">Enregistrer</button>
              <button type="button" onClick={() => setPrForm(null)} className="px-3 py-1.5 text-sm rounded-md border border-gray-300">Annuler</button>
            </div>
          </div>
        )}
        {profils.length === 0 && !prForm && <p className="text-xs text-gray-400 italic">Aucun profil. Commence par « Facture » ou « Courrier administratif ».</p>}
        <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">
          {profils.map(p => (
            <li key={p.id} className="flex items-center gap-2 px-3 py-2 text-sm">
              <span className="text-lg w-7 text-center shrink-0">{p.icone || '📄'}</span>
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{p.nom}
                  {!p.actif && <span className="ml-2 text-xs text-gray-400">(inactif)</span>}
                  <span className="ml-2 text-xs font-normal text-gray-500">{p.classement === 'fixe' ? 'rangé aussitôt' : 'sur confirmation'}</span>
                </div>
                <div className="text-xs text-gray-500 truncate flex items-center gap-1"><ChevronRight size={11} /> {p.destination}{p.tags.length ? ` · tags : ${p.tags.join(', ')}` : ''}</div>
              </div>
              <button type="button" onClick={() => setPrForm({ ...p, icone: p.icone || '' })} className="p-1 text-gray-400 hover:text-blue-600" title="Modifier"><Pencil size={14} /></button>
              <button type="button" onClick={() => supprimerProfil(p)} className="p-1 text-gray-400 hover:text-red-600" title="Supprimer"><Trash2 size={14} /></button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
