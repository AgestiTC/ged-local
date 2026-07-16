/**
 * Page Regroupements — groupes PERSISTANTS de documents + analyse IA formatée.
 * Liste à gauche, détail à droite : documents, prompt/modèle, « Analyser » (tâche durable)
 * → rendu markdown stocké, exportable PDF/DOCX. Backend : /api/regroupements (+ /analyser).
 */
import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Layers, FileText, Trash2, Play, Loader2, RefreshCw, FileDown, FileType2 } from 'lucide-react'
import { clsx } from 'clsx'
import {
  regroupementsApi, systemApi, exportApi, suivreJob,
  type RegroupementResume, type RegroupementDetail, type OllamaModel,
} from '../api'
import { useToast } from '../components/common/Toast'
import LoadingSpinner from '../components/common/LoadingSpinner'

export default function RegroupementsPage() {
  const toast = useToast()
  const [groupes, setGroupes] = useState<RegroupementResume[]>([])
  const [loading, setLoading] = useState(true)
  const [selId, setSelId] = useState<string | null>(null)
  const [detail, setDetail] = useState<RegroupementDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('')
  const [models, setModels] = useState<OllamaModel[]>([])
  const [analysing, setAnalysing] = useState(false)

  const charger = () => {
    setLoading(true)
    regroupementsApi.list().then(setGroupes).catch(() => toast.error('Chargement impossible')).finally(() => setLoading(false))
  }
  useEffect(() => { charger() }, [])
  useEffect(() => { systemApi.models().then(r => setModels(r.models)).catch(() => {}) }, [])

  const ouvrir = async (id: string) => {
    setSelId(id); setLoadingDetail(true); setDetail(null)
    try {
      const d = await regroupementsApi.get(id)
      setDetail(d)
      setPrompt(d.prompt ?? '')
      setModel(d.modele ?? '')
    } catch { toast.error('Détail indisponible') } finally { setLoadingDetail(false) }
  }

  const supprimer = async (id: string) => {
    try {
      await regroupementsApi.remove(id)
      toast.success('Regroupement supprimé')
      if (selId === id) { setSelId(null); setDetail(null) }
      charger()
    } catch { toast.error('Suppression échouée') }
  }

  const analyser = async () => {
    if (!detail) return
    setAnalysing(true)
    try {
      // Persiste prompt/modèle du groupe puis lance l'analyse (tâche durable).
      await regroupementsApi.update(detail.id, { prompt: prompt || undefined, modele: model || undefined })
      const { job_id } = await regroupementsApi.analyser(detail.id, prompt || undefined, model || undefined)
      const job = await suivreJob(job_id)
      if (job.statut === 'completed') {
        toast.success('Analyse terminée')
        await ouvrir(detail.id)   // recharge le rendu stocké
        charger()
      } else {
        toast.error(`Analyse échouée : ${job.erreur ?? 'Ollama ?'}`)
      }
    } catch { toast.error('Analyse impossible (Ollama ?)') } finally { setAnalysing(false) }
  }

  const exporter = async (fmt: 'pdf' | 'docx') => {
    if (!detail?.dernier_rendu) return
    const titre = detail.nom || 'Regroupement'
    try {
      if (fmt === 'pdf') await exportApi.toPdf(detail.dernier_rendu, titre)
      else await exportApi.toDocx(detail.dernier_rendu, titre)
    } catch { toast.error('Export impossible') }
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Liste des regroupements */}
      <aside className="w-72 shrink-0 border-r border-gray-200 bg-white flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <h1 className="text-sm font-semibold flex items-center gap-1.5"><Layers size={16} className="text-blue-600" /> Regroupements</h1>
          <button type="button" onClick={charger} title="Rafraîchir" className="text-gray-400 hover:text-gray-600"><RefreshCw size={14} /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {loading && <LoadingSpinner label="Chargement…" className="py-6 justify-center" />}
          {!loading && groupes.length === 0 && (
            <p className="text-xs text-gray-400 p-3 text-center">
              Aucun regroupement. Sélectionne des documents dans la GED puis « Créer un regroupement ».
            </p>
          )}
          {groupes.map(g => (
            <button key={g.id} type="button" onClick={() => ouvrir(g.id)}
              className={clsx('w-full text-left px-3 py-2 rounded-lg border transition-colors',
                selId === g.id ? 'border-blue-400 bg-blue-50' : 'border-transparent hover:bg-gray-50')}>
              <p className="text-sm font-medium text-gray-800 truncate">{g.nom}</p>
              <p className="text-xs text-gray-400">
                {g.nb_documents} doc{g.nb_documents > 1 ? 's' : ''}
                {g.dernier_analyse_at && ` · analysé le ${new Date(g.dernier_analyse_at).toLocaleDateString('fr-FR')}`}
              </p>
            </button>
          ))}
        </div>
      </aside>

      {/* Détail */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {!selId && (
          <div className="flex-1 flex flex-col items-center justify-center text-gray-300 gap-3">
            <Layers size={48} strokeWidth={1} />
            <p className="text-sm">Choisis un regroupement pour l'analyser</p>
          </div>
        )}
        {selId && loadingDetail && <LoadingSpinner label="Chargement…" className="py-12 justify-center" />}
        {selId && detail && !loadingDetail && (
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold text-gray-800">{detail.nom}</h2>
                {detail.description && <p className="text-sm text-gray-500">{detail.description}</p>}
              </div>
              <button type="button" onClick={() => supprimer(detail.id)}
                className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 rounded-lg border border-red-200 text-red-600 hover:bg-red-50 shrink-0">
                <Trash2 size={14} /> Supprimer
              </button>
            </div>

            {/* Documents du groupe */}
            <div className="bg-white border border-gray-200 rounded-lg p-3">
              <p className="text-xs font-semibold text-gray-500 uppercase mb-2">{detail.documents.length} document(s)</p>
              <div className="flex flex-wrap gap-1.5">
                {detail.documents.map(d => (
                  <span key={d.id} className="inline-flex items-center gap-1 text-xs px-2 py-1 bg-gray-100 text-gray-600 rounded-full">
                    <FileText size={11} className="text-gray-400" /> {d.nom}
                  </span>
                ))}
              </div>
            </div>

            {/* Consigne d'analyse + modèle */}
            <div className="bg-white border border-gray-200 rounded-lg p-3 space-y-2">
              <label className="text-xs font-semibold text-gray-500 uppercase">Consigne d'analyse (propre à ce regroupement)</label>
              <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={3}
                placeholder="Ex : Compare ces devis point par point et fais ressortir le meilleur rapport qualité/prix."
                className="w-full text-sm border border-gray-200 rounded-lg p-2.5 resize-none outline-none focus:border-blue-300 text-gray-700" />
              <div className="flex items-center gap-2 flex-wrap">
                <select value={model} onChange={e => setModel(e.target.value)}
                  className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 text-gray-700">
                  <option value="">Modèle : auto (routage par usage)</option>
                  {models.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
                </select>
                <button type="button" onClick={analyser} disabled={analysing || !prompt.trim()}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40">
                  {analysing ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
                  {analysing ? 'Analyse en cours…' : 'Analyser'}
                </button>
              </div>
            </div>

            {/* Rendu */}
            {detail.dernier_rendu ? (
              <div className="bg-white border border-gray-200 rounded-lg">
                <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100">
                  <span className="text-xs text-gray-500">
                    Dernier rendu{detail.dernier_analyse_at && ` — ${new Date(detail.dernier_analyse_at).toLocaleString('fr-FR')}`}
                    {detail.dernier_modele && ` · ${detail.dernier_modele}`}
                  </span>
                  <div className="flex items-center gap-1">
                    <button type="button" onClick={() => exporter('pdf')} className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded"><FileDown size={13} /> PDF</button>
                    <button type="button" onClick={() => exporter('docx')} className="flex items-center gap-1 text-xs px-2 py-1 text-gray-500 hover:bg-gray-50 rounded"><FileType2 size={13} /> DOCX</button>
                  </div>
                </div>
                <div className="p-4 prose prose-sm max-w-none prose-headings:font-semibold prose-headings:text-gray-800 prose-p:text-gray-700 prose-li:text-gray-700">
                  <ReactMarkdown>{detail.dernier_rendu}</ReactMarkdown>
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-400 text-center py-6">Pas encore d'analyse — saisis une consigne puis « Analyser ».</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
