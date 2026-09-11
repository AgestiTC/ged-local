/**
 * ScanModal — lancer une numérisation depuis Matothèque
 * ======================================================
 * scanner → profil → réglages → « Scanner ». Le backend pilote l'appareil (eSCL) dans une
 * tâche durable ; la modale suit le job. Sur une VITRE, chaque passage rend une page : on
 * enchaîne « Ajouter une page » puis « Terminer » (assemblage, OCR, rangement). Sur un
 * CHARGEUR, tout part d'un coup.
 */
import { useEffect, useMemo, useState } from 'react'
import { Loader2, ScanLine, X } from 'lucide-react'
import { scanApi, suivreJob, extractApiError, type Scanner, type ScanProfil, type ScanReglages, type JobInfo } from '../../api'
import { useToast } from '../common/Toast'

type Etape = 'config' | 'capture' | 'pages' | 'finalisation' | 'fini'

interface Props { open: boolean; onClose: () => void; onDone?: () => void }

export default function ScanModal({ open, onClose, onDone }: Props) {
  const toast = useToast()
  const [scanners, setScanners] = useState<Scanner[]>([])
  const [profils, setProfils] = useState<ScanProfil[]>([])
  const [scannerId, setScannerId] = useState('')
  const [profilId, setProfilId] = useState('')
  const [reglages, setReglages] = useState<ScanReglages>({ source: 'vitre', couleur: 'couleur', dpi: 300, recto_verso: false })
  const [etape, setEtape] = useState<Etape>('config')
  const [scanId, setScanId] = useState<string | null>(null)
  const [pages, setPages] = useState(0)
  const [progress, setProgress] = useState<JobInfo | null>(null)
  const [resultat, setResultat] = useState<Record<string, unknown> | null>(null)
  // Un échec reste AFFICHÉ dans la modale (un toast disparaît avant qu'on l'ait lu).
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setEtape('config'); setScanId(null); setPages(0); setProgress(null); setResultat(null); setErreur(null)
    Promise.all([scanApi.scanners(), scanApi.profils()]).then(([s, p]) => {
      const actifs = s.filter(x => x.actif)
      setScanners(actifs); setProfils(p.filter(x => x.actif))
      if (actifs.length && !scannerId) setScannerId(actifs[0].id)
    }).catch(() => toast.error('Impossible de charger les scanners'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Choisir un profil applique ses réglages et son scanner par défaut.
  const choisirProfil = (id: string) => {
    setProfilId(id)
    const p = profils.find(x => x.id === id)
    if (p) {
      setReglages(r => ({ ...r, ...p.reglages }))
      if (p.scanner_id && scanners.some(s => s.id === p.scanner_id)) setScannerId(p.scanner_id)
    }
  }

  const scanner = useMemo(() => scanners.find(s => s.id === scannerId), [scanners, scannerId])
  const caps = scanner?.capacites
  const chargeurDispo = !caps || caps.chargeur
  const vitreDispo = !caps || caps.vitre
  const source = reglages.source === 'chargeur' && chargeurDispo ? 'chargeur' : 'vitre'
  const resolutions = caps?.resolutions?.length ? caps.resolutions : [150, 200, 300, 600]

  const suivre = async (jobId: string) => {
    const job = await suivreJob(jobId, setProgress, 1200)
    if (job.statut !== 'completed') throw new Error(job.erreur || 'Numérisation interrompue')
    return job
  }

  const lancer = async () => {
    if (!scannerId) return
    setEtape('capture'); setProgress(null); setErreur(null)
    try {
      const finaliser = source === 'chargeur'
      const r = await scanApi.lancer({ scanner_id: scannerId, profil_id: profilId || null, reglages: { ...reglages, source }, finaliser })
      setScanId(r.scan_id)
      const job = await suivre(r.job_id)
      if (finaliser) { setResultat(job.resultat); setEtape('fini'); onDone?.() }
      else { setPages(Number(job.resultat?.pages ?? 1)); setEtape('pages') }
    } catch (e) { const m = extractApiError(e, 'Numérisation impossible'); setErreur(m); toast.error(m); setEtape(scanId ? 'pages' : 'config') }
  }

  const pageSuivante = async () => {
    if (!scanId) return
    setEtape('capture'); setProgress(null); setErreur(null)
    try {
      const r = await scanApi.pageSuivante(scanId)
      const job = await suivre(r.job_id)
      setPages(Number(job.resultat?.pages ?? pages + 1)); setEtape('pages')
    } catch (e) { const m = extractApiError(e, 'Numérisation impossible'); setErreur(m); toast.error(m); setEtape('pages') }
  }

  const terminer = async () => {
    if (!scanId) return
    setEtape('finalisation'); setProgress(null); setErreur(null)
    try {
      const r = await scanApi.terminer(scanId)
      const job = await suivre(r.job_id)
      setResultat(job.resultat); setEtape('fini'); onDone?.()
    } catch (e) { const m = extractApiError(e, 'Finalisation impossible'); setErreur(m); toast.error(m); setEtape('pages') }
  }

  if (!open) return null
  const input = 'w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md bg-white'
  const label = 'block text-xs font-medium text-gray-600 mb-0.5'
  const occupe = etape === 'capture' || etape === 'finalisation'

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => !occupe && onClose()}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-5" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold flex items-center gap-2"><ScanLine size={18} className="text-teal-600" /> Scanner vers la GED</h2>
          <button type="button" onClick={onClose} disabled={occupe} className="p-1 text-gray-400 hover:text-gray-700 disabled:opacity-40"><X size={18} /></button>
        </div>

        {erreur && !occupe && (
          <div className="mb-3 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-sm text-red-800">
            <strong>Échec :</strong> {erreur}
            <div className="text-xs text-red-700 mt-0.5">Le détail est aussi sur la ligne du scan dans la boîte. Corrige la cause puis relance.</div>
          </div>
        )}
        {scanners.length === 0 && (
          <p className="text-sm text-gray-600">Aucun scanner déclaré. Ajoute-en un dans <strong>Paramètres → Scanners &amp; profils de scan</strong>.</p>
        )}

        {etape === 'config' && scanners.length > 0 && (
          <div className="space-y-3">
            <div><label className={label}>Scanner</label>
              <select className={input} value={scannerId} onChange={e => setScannerId(e.target.value)}>
                {scanners.map(s => <option key={s.id} value={s.id}>{s.nom}{s.capacites?.modele ? ` — ${s.capacites.modele}` : ''}</option>)}
              </select>
              {scanner && !scanner.capacites && <p className="text-xs text-amber-600 mt-1">Scanner jamais testé : les réglages seront envoyés tels quels.</p>}
            </div>
            <div><label className={label}>Profil (où ranger, quels tags)</label>
              <select className={input} value={profilId} onChange={e => choisirProfil(e.target.value)}>
                <option value="">— sans profil : reste dans la boîte à scans —</option>
                {profils.map(p => <option key={p.id} value={p.id}>{p.icone ? `${p.icone} ` : ''}{p.nom} → {p.destination}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <div><label className={label}>Source</label>
                <select className={input} value={source} onChange={e => setReglages({ ...reglages, source: e.target.value as 'vitre' | 'chargeur' })}>
                  {vitreDispo && <option value="vitre">Vitre (page à page)</option>}
                  {chargeurDispo && <option value="chargeur">Chargeur (liasse)</option>}
                </select></div>
              <div><label className={label}>Couleur</label>
                <select className={input} value={reglages.couleur || 'couleur'} onChange={e => setReglages({ ...reglages, couleur: e.target.value as 'couleur' | 'gris' | 'nb' })}>
                  <option value="couleur">Couleur</option><option value="gris">Gris</option><option value="nb">Noir et blanc</option>
                </select></div>
              <div><label className={label}>Résolution</label>
                <select className={input} value={reglages.dpi || 300} onChange={e => setReglages({ ...reglages, dpi: Number(e.target.value) })}>
                  {resolutions.map(d => <option key={d} value={d}>{d} dpi</option>)}
                </select></div>
              <div className="flex items-end pb-1.5">
                <label className={`flex items-center gap-1.5 text-sm ${source !== 'chargeur' || (caps && !caps.recto_verso) ? 'text-gray-400' : ''}`}>
                  <input type="checkbox" checked={!!reglages.recto_verso} disabled={source !== 'chargeur' || (!!caps && !caps.recto_verso)}
                    onChange={e => setReglages({ ...reglages, recto_verso: e.target.checked })} /> Recto-verso
                </label>
              </div>
            </div>
            <button type="button" onClick={lancer} disabled={!scannerId}
              className="w-full py-2.5 rounded-lg bg-teal-600 text-white font-medium hover:bg-teal-700 disabled:opacity-60 flex items-center justify-center gap-2">
              <ScanLine size={18} /> Scanner
            </button>
          </div>
        )}

        {occupe && (
          <div className="py-6 text-center space-y-3">
            <Loader2 size={28} className="animate-spin mx-auto text-teal-600" />
            <p className="text-sm text-gray-700">{progress?.progress_message || (etape === 'capture' ? 'Numérisation en cours…' : 'Assemblage, OCR et rangement…')}</p>
            <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden"><div className="h-full bg-teal-500 transition-all" style={{ width: `${progress?.progress ?? 5}%` }} /></div>
            <p className="text-xs text-gray-400">Tu peux fermer la page : la tâche continue côté serveur et le résultat arrive dans la page Scans.</p>
          </div>
        )}

        {etape === 'pages' && scanId && (
          <div className="space-y-3">
            <p className="text-sm text-gray-700"><strong>{pages}</strong> page{pages > 1 ? 's' : ''} capturée{pages > 1 ? 's' : ''}.</p>
            <div className="flex gap-2 overflow-x-auto">
              {Array.from({ length: pages }, (_, i) => i + 1).map(n => (
                <img key={n} src={scanApi.pageUrl(scanId, n)} alt={`page ${n}`} className="h-28 border border-gray-200 rounded shadow-sm bg-white object-contain" />
              ))}
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={pageSuivante} className="flex-1 py-2 rounded-lg border border-teal-600 text-teal-700 hover:bg-teal-50">Ajouter une page</button>
              <button type="button" onClick={terminer} className="flex-1 py-2 rounded-lg bg-teal-600 text-white hover:bg-teal-700">Terminer</button>
            </div>
            <p className="text-xs text-gray-500">Pose la page suivante sur la vitre avant « Ajouter une page ». « Terminer » assemble le PDF, lance l'OCR et range selon le profil.</p>
          </div>
        )}

        {etape === 'fini' && (
          <div className="space-y-3">
            <p className="text-sm text-gray-800">
              ✅ {Number(resultat?.pages ?? 0)} page(s) indexée(s).{' '}
              {resultat?.range ? <>Rangé dans <code className="text-xs bg-gray-100 px-1 rounded">{String(resultat.chemin)}</code>.</>
                : resultat?.erreur ? <span className="text-amber-700">Indexé, mais non rangé : {String(resultat.erreur)}</span>
                : 'En attente dans la boîte à scans (choisis un profil pour ranger).'}
            </p>
            <div className="flex gap-2">
              <button type="button" onClick={() => { setEtape('config'); setScanId(null); setPages(0); setResultat(null); setErreur(null) }} className="flex-1 py-2 rounded-lg border border-gray-300 hover:bg-gray-50">Scanner un autre</button>
              <button type="button" onClick={onClose} className="flex-1 py-2 rounded-lg bg-gray-900 text-white">Fermer</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
