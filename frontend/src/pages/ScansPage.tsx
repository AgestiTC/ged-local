/**
 * Page Scans — la boîte à scans
 * =============================
 * Tout scan y passe : capturé depuis Matothèque (eSCL) ou déposé dans le dossier de la
 * boîte par le bouton de l'appareil. Chaque ligne dit où il en est (numérisation, OCR,
 * indexé, rangé), propose un profil quand l'IA a reconnu quelque chose, et permet de
 * ranger — ou de corriger un rangement avant qu'il parte. Un scan rangé est un document
 * GED comme un autre ; on ne l'affiche plus ici sauf à le demander.
 */
import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Eye, EyeOff, Loader2, RefreshCw, ScanLine, Settings, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { clsx } from 'clsx'
import { scanApi, suivreJob, extractApiError, type ScanItem, type ScanProfil } from '../api'
import ScanModal from '../components/ged/ScanModal'
import { useToast } from '../components/common/Toast'

const STATUTS: Record<ScanItem['statut'], { label: string; cls: string }> = {
  en_cours: { label: 'numérisation', cls: 'bg-blue-100 text-blue-700' },
  recu: { label: 'reçu, OCR en cours', cls: 'bg-amber-100 text-amber-700' },
  indexe: { label: 'indexé, à ranger', cls: 'bg-violet-100 text-violet-700' },
  range: { label: 'rangé', cls: 'bg-emerald-100 text-emerald-700' },
  erreur: { label: 'erreur', cls: 'bg-red-100 text-red-700' },
}

function quand(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export default function ScansPage() {
  const toast = useToast()
  const [items, setItems] = useState<ScanItem[]>([])
  const [profils, setProfils] = useState<ScanProfil[]>([])
  const [boite, setBoite] = useState('')
  const [tout, setTout] = useState(false)
  const [loading, setLoading] = useState(true)
  const [modal, setModal] = useState(false)
  const [choix, setChoix] = useState<Record<string, { profil_id: string; nom: string }>>({})
  const [busy, setBusy] = useState<string | null>(null)

  const charger = useCallback(async (silencieux = false) => {
    if (!silencieux) setLoading(true)
    try {
      const [r, p] = await Promise.all([scanApi.inbox(tout), scanApi.profils()])
      setItems(r.scans); setBoite(r.boite_chemin); setProfils(p.filter(x => x.actif))
    } catch (e) { if (!silencieux) toast.error(extractApiError(e, 'Chargement impossible')) } finally { setLoading(false) }
  }, [tout, toast])
  useEffect(() => { void charger() }, [charger])

  // Tant qu'un scan est en cours / en OCR, on relit toutes les 4 s.
  useEffect(() => {
    if (!items.some(i => i.statut === 'en_cours' || i.statut === 'recu')) return
    const t = setInterval(() => void charger(true), 4000)
    return () => clearInterval(t)
  }, [items, charger])

  const profilChoisi = (it: ScanItem) => choix[it.id]?.profil_id ?? it.proposition?.profil_id ?? it.profil_id ?? ''

  const ranger = async (it: ScanItem) => {
    const pid = profilChoisi(it)
    if (!pid) { toast.info('Choisis un profil'); return }
    setBusy(it.id)
    try {
      const r = await scanApi.ranger(it.id, { profil_id: pid, nom: choix[it.id]?.nom || null })
      const job = await suivreJob(r.job_id, undefined, 1000)
      if (job.statut === 'completed') toast.success(`Rangé : ${String(job.resultat?.nom ?? '')}`)
      else toast.error(job.erreur || 'Rangement échoué')
      await charger(true)
    } catch (e) { toast.error(extractApiError(e, 'Rangement impossible')) } finally { setBusy(null) }
  }

  const retirer = async (it: ScanItem) => {
    if (!window.confirm('Retirer cette ligne de la boîte ? Le document, lui, reste dans la GED.')) return
    try { await scanApi.retirer(it.id); await charger(true) } catch (e) { toast.error(extractApiError(e)) }
  }

  return (
    <div className="p-3 sm:p-6 max-w-5xl mx-auto">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2"><ScanLine size={20} className="text-teal-600" /> Scans</h1>
          <p className="text-sm text-gray-500">
            La boîte à scans : ce qui vient d'être numérisé, où ça en est, et où le ranger.
            {boite ? <> Dossier de dépôt : <code className="text-xs bg-gray-100 px-1 rounded">{boite}</code>.</> : <> Aucun dossier de dépôt configuré (<Link to="/settings?section=set-sources" className="text-blue-600 underline">Paramètres</Link>).</>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setTout(t => !t)} className="flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border border-gray-300 hover:bg-gray-50" title={tout ? 'Masquer les scans rangés' : 'Afficher aussi les scans rangés'}>
            {tout ? <EyeOff size={13} /> : <Eye size={13} />} {tout ? 'Masquer les rangés' : 'Voir les rangés'}
          </button>
          <button type="button" onClick={() => void charger()} className="p-1.5 rounded-md border border-gray-300 hover:bg-gray-50" title="Actualiser"><RefreshCw size={14} /></button>
          <Link to="/settings?section=set-sources" className="p-1.5 rounded-md border border-gray-300 hover:bg-gray-50" title="Scanners & profils"><Settings size={14} /></Link>
          <button type="button" onClick={() => setModal(true)} className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-teal-600 text-white hover:bg-teal-700">
            <ScanLine size={15} /> Scanner
          </button>
        </div>
      </div>

      {loading ? (
        <div className="py-16 text-center text-gray-400"><Loader2 className="animate-spin mx-auto" /></div>
      ) : items.length === 0 ? (
        <div className="py-16 text-center text-gray-500 text-sm">
          Rien dans la boîte. Clique <strong>Scanner</strong>, ou dépose un PDF dans le dossier de la boîte.
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map(it => {
            const st = STATUTS[it.statut]
            const pid = profilChoisi(it)
            const peutRanger = it.statut === 'indexe' || (it.statut === 'erreur' && !!it.document)
            return (
              <li key={it.id} className={clsx('border rounded-lg p-3 bg-white', it.statut === 'erreur' ? 'border-red-200' : 'border-gray-200')}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={clsx('text-xs px-2 py-0.5 rounded-full font-medium', st.cls)}>{st.label}</span>
                  <span className="text-xs text-gray-400">{it.origine === 'escl' ? 'depuis Matothèque' : 'déposé dans la boîte'} · {quand(it.created_at)}{it.nb_pages ? ` · ${it.nb_pages} p.` : ''}</span>
                  <span className="flex-1" />
                  {it.document && (
                    <Link to={`/ged?doc=${it.document.id}`} className="text-xs text-blue-600 hover:underline flex items-center gap-1"><Eye size={12} /> voir dans la GED</Link>
                  )}
                  <button type="button" onClick={() => retirer(it)} className="p-1 text-gray-400 hover:text-red-600" title="Retirer de la boîte"><Trash2 size={14} /></button>
                </div>
                {it.document ? (
                  <div className="mt-1.5">
                    <div className="text-sm font-medium truncate">{it.document.nom}</div>
                    <div className="text-xs text-gray-500 truncate">{it.document.chemin}</div>
                    {(it.document.categorie || it.document.tags.length > 0) && (
                      <div className="text-xs text-gray-600 mt-1">
                        {it.document.categorie && <span className="mr-2">catégorie : <strong>{it.document.categorie}</strong></span>}
                        {it.document.tags.map(t => <span key={t} className="inline-block mr-1 px-1.5 py-0.5 bg-gray-100 rounded text-[11px]">{t}</span>)}
                      </div>
                    )}
                  </div>
                ) : it.statut === 'en_cours' ? (
                  <p className="text-sm text-gray-600 mt-1.5 flex items-center gap-1.5"><Loader2 size={13} className="animate-spin" /> Numérisation en cours — pages capturées : {it.nb_pages}</p>
                ) : null}
                {it.erreur && <p className="text-xs text-red-700 mt-1.5 flex items-center gap-1"><AlertTriangle size={12} /> {it.erreur}</p>}
                {it.statut === 'range' && (
                  <p className="text-xs text-emerald-700 mt-1.5 flex items-center gap-1"><CheckCircle2 size={12} /> rangé le {quand(it.range_at)}</p>
                )}

                {peutRanger && (
                  <div className="mt-2 pt-2 border-t border-gray-100 flex flex-wrap items-center gap-2">
                    {it.proposition && !choix[it.id] && (
                      <span className="text-xs text-violet-700" title={it.proposition.raisons.join(' · ')}>
                        proposé : <strong>{it.proposition.nom}</strong> ({it.proposition.raisons.length} indice{it.proposition.raisons.length > 1 ? 's' : ''})
                      </span>
                    )}
                    <select value={pid} onChange={e => setChoix(c => ({ ...c, [it.id]: { profil_id: e.target.value, nom: c[it.id]?.nom || '' } }))}
                      className="text-sm border border-gray-300 rounded-md px-2 py-1 bg-white">
                      <option value="">— profil —</option>
                      {profils.map(p => <option key={p.id} value={p.id}>{p.icone ? `${p.icone} ` : ''}{p.nom} → {p.destination}</option>)}
                    </select>
                    <input value={choix[it.id]?.nom || ''} onChange={e => setChoix(c => ({ ...c, [it.id]: { profil_id: c[it.id]?.profil_id ?? pid, nom: e.target.value } }))}
                      placeholder="nom (optionnel, sinon selon le profil)" className="text-sm border border-gray-300 rounded-md px-2 py-1 flex-1 min-w-[12rem]" />
                    <button type="button" onClick={() => ranger(it)} disabled={busy === it.id || !pid}
                      className="text-sm px-3 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-60 flex items-center gap-1">
                      {busy === it.id ? <Loader2 size={13} className="animate-spin" /> : null} {it.proposition && pid === it.proposition.profil_id && !choix[it.id] ? 'Confirmer' : 'Ranger'}
                    </button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <ScanModal open={modal} onClose={() => setModal(false)} onDone={() => void charger(true)} />
    </div>
  )
}
