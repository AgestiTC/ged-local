/**
 * Page Réorganiser — Réorganisation d'arborescence par IA
 * Phase 2 : l'IA propose une arborescence (persistée), éditable en **drag & drop**
 * (déplacer un document dans un autre dossier). Vue **virtuelle** : AUCUN fichier n'est
 * déplacé — l'application physique au NAS (+ undo) est la Phase 3.
 */
import { useEffect, useState } from 'react'
import { FolderTree, Sparkles, Loader2, Folder, FileText, ChevronRight, ChevronDown, Info, FolderPlus, GripVertical, HardDrive, Undo2, AlertTriangle, Play } from 'lucide-react'
import { clsx } from 'clsx'
import { organizeApi, suivreJob, type OrganizeFolder } from '../api'
import { useToast } from '../components/common/Toast'

export default function ReorganizePage() {
  const toast = useToast()
  const [consigne, setConsigne] = useState('')
  const [inclureAnnee, setInclureAnnee] = useState(true)
  const [loading, setLoading] = useState(false)
  const [criteres, setCriteres] = useState<string | null>(null)
  const [arbo, setArbo] = useState<OrganizeFolder[]>([])
  const [ouverts, setOuverts] = useState<Set<string>>(new Set())
  const [survol, setSurvol] = useState<string | null>(null)   // dossier survolé en drag
  const [nouveauDossier, setNouveauDossier] = useState('')
  // Phase 3 — application physique (NAS)
  const [dryRun, setDryRun] = useState<{ total: number; a_deplacer: number; ignores: number } | null>(null)
  const [confirmApply, setConfirmApply] = useState(false)
  const [applyStatus, setApplyStatus] = useState<string | null>(null)

  // Charge un plan déjà persisté au montage (on peut reprendre l'édition).
  useEffect(() => {
    organizeApi.getPlan().then(p => setArbo(p.arborescence)).catch(() => {})
  }, [])

  const proposer = async () => {
    setLoading(true)
    try {
      const res = await organizeApi.propose(consigne.trim() || undefined, inclureAnnee)
      setCriteres(res.criteres)
      setArbo(res.arborescence)
      if (res.nb_dossiers === 0) toast.info('Aucun document à ranger.')
      else toast.success('Arborescence proposée — édite-la en glissant les documents.')
    } catch {
      toast.error("Échec de la proposition (Ollama injoignable ?)")
    } finally { setLoading(false) }
  }

  const rafraichir = () => organizeApi.getPlan().then(p => setArbo(p.arborescence)).catch(() => {})

  const deplacer = async (ids: string[], dossier: string) => {
    if (!dossier.trim()) return
    try {
      await organizeApi.movePlan(ids, dossier.trim())
      await rafraichir()
    } catch { toast.error('Déplacement impossible') }
  }

  const simuler = async () => {
    try { const r = await organizeApi.dryRun(); setDryRun({ total: r.total, a_deplacer: r.a_deplacer, ignores: r.ignores }) }
    catch { toast.error('Simulation impossible') }
  }
  const appliquer = async () => {
    setConfirmApply(false); setApplyStatus('Démarrage…')
    try {
      const { job_id } = await organizeApi.apply()
      const job = await suivreJob(job_id, p => setApplyStatus(`${p.progress}% — ${p.progress_message ?? ''}`))
      setApplyStatus(null); setDryRun(null)
      if (job.statut === 'completed') {
        const r = job.resultat as { deplaces?: number } | null
        toast.success(`Rangé au NAS — ${r?.deplaces ?? 0} fichier(s) déplacé(s)`) ; rafraichir()
      } else toast.error('Application échouée')
    } catch { setApplyStatus(null); toast.error('Application impossible') }
  }
  const annuler = async () => {
    setApplyStatus('Annulation…')
    try {
      const { job_id } = await organizeApi.undo()
      const job = await suivreJob(job_id, p => setApplyStatus(`${p.progress}% — ${p.progress_message ?? ''}`))
      setApplyStatus(null)
      if (job.statut === 'completed') {
        const r = job.resultat as { remis?: number } | null
        toast.success(`Annulé — ${r?.remis ?? 0} fichier(s) remis`) ; rafraichir()
      } else toast.error('Annulation échouée')
    } catch { setApplyStatus(null); toast.error('Annulation impossible') }
  }

  const toggle = (d: string) => setOuverts(p => { const n = new Set(p); n.has(d) ? n.delete(d) : n.add(d); return n })
  const onDrop = (dossier: string) => (e: React.DragEvent) => {
    e.preventDefault(); setSurvol(null)
    const id = e.dataTransfer.getData('text/plain')
    if (id) deplacer([id], dossier)
  }
  const nbDocs = arbo.reduce((s, f) => s + f.nb, 0)

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-4">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <FolderTree size={20} className="text-blue-600" /> Réorganiser l'arborescence
        </h1>
        <p className="text-sm text-gray-500">
          L'IA propose un rangement ; <strong>glisse les documents</strong> pour l'ajuster.
        </p>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4 text-xs text-blue-800 flex items-start gap-2">
        <Info size={15} className="shrink-0 mt-0.5" />
        <span><strong>Vue virtuelle</strong> — le plan est <strong>enregistré</strong> et modifiable, mais
        <strong> aucun fichier n'est déplacé</strong>. L'application au NAS (avec annulation) arrivera en Phase 3.</span>
      </div>

      {/* Contrôles */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3 mb-4">
        <textarea
          value={consigne}
          onChange={e => setConsigne(e.target.value)}
          placeholder="Consigne (optionnel) — ex. « range par client », « par année puis par type »…"
          rows={2}
          className="w-full text-sm border border-gray-200 rounded-md px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
        <div className="flex items-center justify-between flex-wrap gap-2">
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input type="checkbox" checked={inclureAnnee} onChange={e => setInclureAnnee(e.target.checked)} className="w-4 h-4 accent-blue-600" />
            Sous-dossier par année
          </label>
          <button type="button" onClick={proposer} disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {loading ? 'L\'IA réfléchit…' : arbo.length ? 'Reproposer (IA)' : 'Proposer une arborescence (IA)'}
          </button>
        </div>
      </div>

      {criteres && (
        <div className="bg-white border border-gray-200 rounded-lg p-3 mb-3 text-sm text-gray-700">
          <p className="flex items-center gap-1.5"><Sparkles size={14} className="text-blue-500" /> <strong>Critère IA</strong></p>
          <p className="mt-1 italic text-gray-600">{criteres}</p>
        </div>
      )}

      {/* Phase 3 — application physique au NAS (dry-run / appliquer / annuler) */}
      {arbo.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-3 mb-3 flex items-center gap-2 flex-wrap">
          <button type="button" onClick={simuler}
            className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">
            <Play size={14} /> Simuler (dry-run)
          </button>
          {dryRun && <span className="text-xs text-gray-500">{dryRun.a_deplacer} à déplacer · {dryRun.ignores} ignorés (non-SMB)</span>}
          <div className="flex-1" />
          {applyStatus ? (
            <span className="flex items-center gap-2 text-sm text-blue-600"><Loader2 size={14} className="animate-spin" /> {applyStatus}</span>
          ) : (
            <>
              <button type="button" onClick={annuler}
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50">
                <Undo2 size={14} /> Annuler la dernière
              </button>
              <button type="button" onClick={() => setConfirmApply(true)}
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-red-600 text-white hover:bg-red-700">
                <HardDrive size={14} /> Appliquer au NAS
              </button>
            </>
          )}
        </div>
      )}

      {arbo.length > 0 ? (
        <>
          <p className="text-xs text-gray-400 mb-2">{nbDocs} document(s) · {arbo.length} dossier(s) — glisse un document sur un dossier pour le déplacer.</p>
          <div className="space-y-1.5">
            {arbo.map(f => (
              <div key={f.dossier}
                onDragOver={e => { e.preventDefault(); setSurvol(f.dossier) }}
                onDragLeave={() => setSurvol(s => (s === f.dossier ? null : s))}
                onDrop={onDrop(f.dossier)}
                className={clsx('border rounded-lg overflow-hidden transition-colors',
                  survol === f.dossier ? 'border-blue-400 bg-blue-50/60' : 'border-gray-200')}>
                <button type="button" onClick={() => toggle(f.dossier)}
                  className="flex items-center gap-2 w-full px-3 py-2 text-left text-sm hover:bg-gray-50">
                  {ouverts.has(f.dossier) ? <ChevronDown size={14} className="text-gray-400" /> : <ChevronRight size={14} className="text-gray-400" />}
                  <Folder size={15} className="text-amber-500 shrink-0" />
                  <span className="font-medium flex-1 truncate">{f.dossier}</span>
                  <span className="text-xs text-gray-400 shrink-0">{f.nb}</span>
                </button>
                {ouverts.has(f.dossier) && (
                  <ul className="border-t border-gray-100 divide-y divide-gray-50 bg-gray-50/50">
                    {f.documents.map(doc => (
                      <li key={doc.id} draggable
                        onDragStart={e => { e.dataTransfer.setData('text/plain', doc.id); e.dataTransfer.effectAllowed = 'move' }}
                        className="flex items-center gap-2 px-3 py-1.5 pl-6 text-sm text-gray-600 cursor-grab active:cursor-grabbing hover:bg-white">
                        <GripVertical size={12} className="text-gray-300 shrink-0" />
                        <FileText size={13} className="text-gray-400 shrink-0" />
                        <span className="truncate flex-1">{doc.nom}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}

            {/* Zone « nouveau dossier » : dépose un document ici pour le ranger dans un dossier créé. */}
            <div
              onDragOver={e => { if (nouveauDossier.trim()) { e.preventDefault(); setSurvol('__new__') } }}
              onDrop={e => { if (nouveauDossier.trim()) onDrop(nouveauDossier.trim())(e) }}
              className={clsx('border-2 border-dashed rounded-lg p-3 flex items-center gap-2 transition-colors',
                survol === '__new__' ? 'border-blue-400 bg-blue-50/60' : 'border-gray-200')}>
              <FolderPlus size={15} className="text-gray-400 shrink-0" />
              <input value={nouveauDossier} onChange={e => setNouveauDossier(e.target.value)}
                placeholder="Nouveau dossier (ex. Factures/2025) — puis glisse un document ici"
                className="flex-1 text-sm bg-transparent focus:outline-none" />
            </div>
          </div>
        </>
      ) : !loading && (
        <div className="text-center text-gray-400 py-16">
          <FolderTree size={40} strokeWidth={1} className="mx-auto mb-3" />
          <p>Lance une proposition pour voir l'arborescence suggérée.</p>
        </div>
      )}

      {/* Confirmation — déplacement PHYSIQUE au NAS (destructif, réversible via Annuler) */}
      {confirmApply && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => setConfirmApply(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2"><AlertTriangle size={18} className="text-red-600" /> Appliquer au NAS</h2>
            <p className="text-sm text-gray-600 mb-3">
              Les fichiers vont être <strong>réellement déplacés</strong> sur le NAS selon ce plan
              {dryRun ? <> (<strong>{dryRun.a_deplacer}</strong> fichier(s))</> : null}. <strong>Jamais de
              suppression</strong> ; tu pourras <strong>annuler</strong> (les fichiers reviendront à leur place).
            </p>
            <p className="text-xs text-gray-400 mb-4">Conseil : lance d'abord <strong>« Simuler »</strong> pour vérifier.</p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setConfirmApply(false)}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50">Annuler</button>
              <button type="button" onClick={appliquer}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700">
                <HardDrive size={15} /> Confirmer le déplacement
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
