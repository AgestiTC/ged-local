/**
 * Page Réorganiser — Réorganisation d'arborescence par IA (incrément 1 : aperçu)
 * L'IA propose une arborescence cible à partir des métadonnées ; on l'affiche en
 * APERÇU (lecture seule). L'édition drag & drop + l'application (vue virtuelle puis
 * déplacement physique au NAS) arrivent en incrément 2.
 */
import { useState } from 'react'
import { FolderTree, Sparkles, Loader2, Folder, FileText, ChevronRight, ChevronDown, Info } from 'lucide-react'
import { organizeApi, type OrganizeProposal } from '../api'
import { useToast } from '../components/common/Toast'

export default function ReorganizePage() {
  const toast = useToast()
  const [consigne, setConsigne] = useState('')
  const [inclureAnnee, setInclureAnnee] = useState(true)
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<OrganizeProposal | null>(null)
  const [ouverts, setOuverts] = useState<Set<string>>(new Set())

  const proposer = async () => {
    setLoading(true); setData(null)
    try {
      const res = await organizeApi.propose(consigne.trim() || undefined, inclureAnnee)
      setData(res)
      if (res.nb_dossiers === 0) toast.info('Aucun document à ranger.')
    } catch {
      toast.error("Échec de la proposition (Ollama injoignable ?)")
    } finally { setLoading(false) }
  }

  const toggle = (d: string) => setOuverts(p => { const n = new Set(p); n.has(d) ? n.delete(d) : n.add(d); return n })

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-4">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <FolderTree size={20} className="text-blue-600" /> Réorganiser l'arborescence
        </h1>
        <p className="text-sm text-gray-500">
          L'IA propose un rangement de tes documents par dossiers. Tu peux orienter avec une consigne.
        </p>
      </div>

      {/* Bandeau incrément */}
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4 text-xs text-amber-800 flex items-start gap-2">
        <Info size={15} className="shrink-0 mt-0.5" />
        <span><strong>Aperçu uniquement</strong> pour l'instant — rien n'est déplacé. L'édition (drag & drop)
        et l'application (vue virtuelle, puis déplacement au NAS avec annulation) arrivent ensuite.</span>
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
          <button
            type="button" onClick={proposer} disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {loading ? 'L\'IA réfléchit…' : 'Proposer une arborescence (IA)'}
          </button>
        </div>
      </div>

      {/* Résultat */}
      {data && (
        <>
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-3 text-sm text-blue-800">
            <p className="flex items-center gap-1.5"><Sparkles size={14} /> <strong>Proposition IA</strong></p>
            <p className="mt-1 italic">{data.criteres}</p>
            <p className="mt-1 text-xs text-blue-600">{data.nb_documents} document(s) · {data.nb_dossiers} dossier(s)</p>
          </div>

          <div className="space-y-1.5 pb-10">
            {data.arborescence.map(f => (
              <div key={f.dossier} className="border border-gray-200 rounded-lg overflow-hidden">
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
                      <li key={doc.id} className="flex items-center gap-2 px-3 py-1.5 pl-9 text-sm text-gray-600">
                        <FileText size={13} className="text-gray-400 shrink-0" />
                        <span className="truncate flex-1">{doc.nom}</span>
                        <span className="text-xs text-gray-300 shrink-0">{doc.categorie}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {!data && !loading && (
        <div className="text-center text-gray-400 py-16">
          <FolderTree size={40} strokeWidth={1} className="mx-auto mb-3" />
          <p>Lance une proposition pour voir l'arborescence suggérée.</p>
        </div>
      )}
    </div>
  )
}
