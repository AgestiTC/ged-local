/**
 * AbsentsModal — revue et purge des documents « disparus » (statut='absent')
 * ==========================================================================
 * Les fichiers supprimés du NAS sont marqués `absent` par la synchro, JAMAIS supprimés d'office.
 * Cette modale les liste et permet de les retirer de l'index (sélection ou tout), après
 * confirmation. Ne touche à aucun fichier — l'index se reconstruit s'ils reviennent.
 */
import { useCallback, useEffect, useState } from 'react'
import { X, Trash2, Loader2, FileX } from 'lucide-react'
import { clsx } from 'clsx'
import { sourcesApi, extractApiError, type Source } from '../../api'
import { useToast } from '../common/Toast'

interface Doc { id: string; nom: string; chemin: string; date: string | null }

export default function AbsentsModal({ source, onClose, onPurge }: {
  source: Source; onClose: () => void; onPurge: () => void
}) {
  const toast = useToast()
  const [docs, setDocs] = useState<Doc[]>([])
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const charger = useCallback(async () => {
    setLoading(true)
    try {
      const d = await sourcesApi.absents(source.id)
      setDocs(d.documents); setSel(new Set())
    } catch (e) { toast.error(extractApiError(e, 'Chargement impossible')) }
    finally { setLoading(false) }
  }, [source.id, toast])
  useEffect(() => { charger() }, [charger])

  const toutSel = sel.size > 0 && sel.size === docs.length
  const toggle = (id: string) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const purger = async (tout: boolean) => {
    const n = tout ? docs.length : sel.size
    if (n === 0) return
    if (!confirm(`Retirer ${n} document(s) disparu(s) de l'index ? Les fichiers ne sont pas touchés ; l'index se reconstruit s'ils reviennent.`)) return
    setBusy(true)
    try {
      const { retires } = await sourcesApi.purgeAbsents(source.id, tout ? [] : [...sel], tout)
      toast.success(`${retires} document(s) retiré(s) de l'index`)
      onPurge()
      await charger()
      if (docs.length - retires <= 0) onClose()
    } catch (e) { toast.error(extractApiError(e, 'Purge impossible')) }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <FileX size={16} className="text-amber-600" /> Documents disparus — {source.libelle}
          </h3>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700"><X size={16} /></button>
        </div>

        <div className="px-4 py-2 border-b border-gray-100 flex items-center gap-2 text-xs">
          <label className="flex items-center gap-1.5 text-gray-600">
            <input type="checkbox" checked={toutSel} disabled={docs.length === 0}
              onChange={() => setSel(toutSel ? new Set() : new Set(docs.map(d => d.id)))}
              className="w-3.5 h-3.5 accent-blue-600" /> Tout sélectionner
          </label>
          <button type="button" onClick={() => purger(false)} disabled={sel.size === 0 || busy}
            className="flex items-center gap-1 px-2 py-1 rounded-md border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40">
            <Trash2 size={12} /> Retirer{sel.size ? ` (${sel.size})` : ''}
          </button>
          <button type="button" onClick={() => purger(true)} disabled={docs.length === 0 || busy}
            className="px-2 py-1 rounded-md text-gray-500 hover:bg-gray-100 disabled:opacity-40">Tout retirer</button>
          <span className="ml-auto text-gray-400">{docs.length} disparu(s)</span>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {loading ? <div className="flex justify-center py-6"><Loader2 size={18} className="animate-spin text-gray-400" /></div>
            : docs.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-6">Aucun document disparu. L'index est à jour avec le NAS.</p>
            ) : (
            <ul className="divide-y divide-gray-100">
              {docs.map(d => (
                <li key={d.id} className={clsx('flex items-start gap-2 py-1.5 px-1 rounded text-xs', sel.has(d.id) ? 'bg-blue-50' : 'hover:bg-gray-50')}>
                  <input type="checkbox" checked={sel.has(d.id)} onChange={() => toggle(d.id)}
                    className="w-3.5 h-3.5 accent-blue-600 mt-0.5 shrink-0" />
                  <div className="min-w-0">
                    <p className="font-medium text-gray-700 truncate">{d.nom}</p>
                    <p className="text-gray-400 truncate">{d.chemin}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="px-4 py-2 border-t border-gray-100 text-[11px] text-gray-400">
          Retirer de l'index ne supprime aucun fichier sur le NAS.
        </div>
      </div>
    </div>
  )
}
