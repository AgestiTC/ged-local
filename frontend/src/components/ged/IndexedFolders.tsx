/**
 * IndexedFolders — Arbre des dossiers RÉELLEMENT indexés d'une source.
 * Dossier parent déplié, sous-dossiers pliés. Cases à cocher + tout cocher/décocher
 * pour RETIRER des dossiers de l'index (désindexer) — ne touche pas aux fichiers du NAS.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Folder, FolderOpen, ChevronRight, ChevronDown, Loader2, Trash2, RefreshCw, X } from 'lucide-react'
import { sourcesApi, type Source, type IndexedNode, type IndexedTree } from '../../api'
import { useToast } from '../common/Toast'

function collectChemins(nodes: IndexedNode[], acc: string[] = []): string[] {
  for (const n of nodes) { acc.push(n.chemin); collectChemins(n.enfants, acc) }
  return acc
}

export default function IndexedFolders({ source, onClose }: { source: Source; onClose: () => void }) {
  const toast = useToast()
  const [tree, setTree] = useState<IndexedTree | null>(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [deindexing, setDeindexing] = useState(false)

  const charger = useCallback(async () => {
    setLoading(true); setSelected(new Set())
    try {
      const t = await sourcesApi.indexed(source.id)
      setTree(t)
      setExpanded(new Set(t.arbre.map(n => n.chemin)))   // niveau 1 déplié, le reste plié
    } catch {
      toast.error("Impossible de charger les dossiers indexés")
    } finally { setLoading(false) }
  }, [source.id, toast])

  useEffect(() => { charger() }, [charger])

  const allChemins = useMemo(() => tree ? collectChemins(tree.arbre) : [], [tree])
  const toggleSel = (c: string) => setSelected(p => { const n = new Set(p); n.has(c) ? n.delete(c) : n.add(c); return n })
  const toggleExp = (c: string) => setExpanded(p => { const n = new Set(p); n.has(c) ? n.delete(c) : n.add(c); return n })

  const confirmer = async () => {
    setDeindexing(true)
    try {
      const r = await sourcesApi.deindex(source.id, [...selected])
      toast.success(`${r.retires} document(s) retiré(s) de l'index`)
      setConfirmOpen(false)
      await charger()
    } catch {
      toast.error("Échec du retrait de l'index")
    } finally { setDeindexing(false) }
  }

  const Row = ({ node, niveau }: { node: IndexedNode; niveau: number }) => {
    const aEnfants = node.enfants.length > 0
    const ouvert = expanded.has(node.chemin)
    return (
      <>
        <div className="flex items-center gap-2 px-2 py-1.5 hover:bg-gray-50" style={{ paddingLeft: `${8 + niveau * 18}px` }}>
          <input type="checkbox" checked={selected.has(node.chemin)} onChange={() => toggleSel(node.chemin)}
            className="w-4 h-4 accent-amber-600 shrink-0" aria-label={`Sélectionner ${node.nom}`} />
          {aEnfants ? (
            <button type="button" onClick={() => toggleExp(node.chemin)} className="text-gray-400 shrink-0">
              {ouvert ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          ) : <span className="w-3.5 shrink-0" />}
          {aEnfants && ouvert ? <FolderOpen size={14} className="text-amber-500 shrink-0" /> : <Folder size={14} className="text-amber-500 shrink-0" />}
          <span className="text-sm truncate flex-1">{node.nom}</span>
          <span className="text-xs text-gray-400 shrink-0">{node.nb}</span>
        </div>
        {aEnfants && ouvert && node.enfants.map(e => <Row key={e.chemin} node={e} niveau={niveau + 1} />)}
      </>
    )
  }

  return (
    <div className="border border-amber-200 rounded-lg p-3 bg-amber-50/30">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium flex items-center gap-1.5">
          <FolderOpen size={15} className="text-amber-600" /> Dossiers indexés — {source.libelle}
          {tree && <span className="text-xs text-gray-400">({tree.nb_documents} doc.)</span>}
        </span>
        <div className="flex items-center gap-2">
          <button type="button" onClick={charger} disabled={loading} title="Rafraîchir" className="p-1 text-gray-400 hover:text-gray-700">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700"><X size={15} /></button>
        </div>
      </div>

      {tree && tree.arbre.length > 0 && (
        <div className="flex items-center justify-end gap-2 text-xs mb-1">
          <button type="button" onClick={() => setSelected(new Set(allChemins))} className="text-amber-700 hover:underline">Tout cocher</button>
          <span className="text-gray-300">·</span>
          <button type="button" onClick={() => setSelected(new Set())} className="text-gray-500 hover:underline">Tout décocher</button>
        </div>
      )}

      <div className="max-h-72 overflow-auto border border-gray-200 rounded-md bg-white">
        {loading && <p className="text-xs text-gray-400 px-2 py-3 flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Chargement…</p>}
        {!loading && tree && tree.arbre.length === 0 && <p className="text-xs text-gray-400 px-2 py-3">Aucun document indexé pour cette source.</p>}
        {!loading && tree?.arbre.map(n => <Row key={n.chemin} node={n} niveau={0} />)}
      </div>

      {selected.size > 0 && (
        <div className="flex justify-end mt-2">
          <button type="button" onClick={() => setConfirmOpen(true)}
            className="flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-red-600 text-white hover:bg-red-700">
            <Trash2 size={15} /> Retirer de l'index ({selected.size})
          </button>
        </div>
      )}

      {confirmOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5">
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2"><Trash2 size={18} className="text-red-600" /> Retirer de l'index</h2>
            <p className="text-sm text-gray-600 mb-4">
              Les documents de <strong>{selected.size}</strong> dossier(s) vont être <strong>retirés de la GED</strong>.
              Les <strong>fichiers sur le NAS ne sont PAS supprimés</strong> — tu pourras les ré-indexer plus tard.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setConfirmOpen(false)} disabled={deindexing}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">Annuler</button>
              <button type="button" onClick={confirmer} disabled={deindexing}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50">
                {deindexing ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />} Retirer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
