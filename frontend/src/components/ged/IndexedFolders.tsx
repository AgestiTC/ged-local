/**
 * IndexedFolders — Arbre des dossiers RÉELLEMENT indexés d'une source.
 * Dossier parent déplié, sous-dossiers pliés. Cases à cocher + tout cocher/décocher
 * pour RETIRER des dossiers de l'index (désindexer) — ne touche pas aux fichiers du NAS.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Folder, FolderOpen, ChevronRight, ChevronDown, Loader2, Trash2, RefreshCw, X } from 'lucide-react'
import { sourcesApi, type Source, type IndexedNode, type IndexedTree } from '../../api'
import { useToast } from '../common/Toast'

// Chemins d'un sous-arbre (le nœud + tous ses descendants) — sert à la cascade et au « tout cocher ».
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
  const scrollRef = useRef<HTMLDivElement>(null)
  const scrollAvant = useRef<number | null>(null)   // scrollTop à restaurer après un rafraîchissement

  // `preserver` = rafraîchissement manuel : on GARDE la sélection, les dépliages et la position de
  // défilement (au lieu de tout remettre à zéro et de remonter en haut). Au 1er chargement / après
  // désindexation, on repart propre (les dossiers retirés n'existent plus).
  const charger = useCallback(async (preserver = false) => {
    if (preserver && scrollRef.current) scrollAvant.current = scrollRef.current.scrollTop
    setLoading(true)
    if (!preserver) setSelected(new Set())
    try {
      const t = await sourcesApi.indexed(source.id)
      setTree(t)
      if (!preserver) setExpanded(new Set(t.arbre.map(n => n.chemin)))   // niveau 1 déplié, reste plié
    } catch {
      toast.error("Impossible de charger les dossiers indexés")
    } finally { setLoading(false) }
  }, [source.id, toast])

  useEffect(() => { charger() }, [charger])

  // Restaure la position de défilement une fois l'arbre re-rendu (rafraîchissement manuel).
  useLayoutEffect(() => {
    if (scrollAvant.current != null && scrollRef.current) {
      scrollRef.current.scrollTop = scrollAvant.current
      scrollAvant.current = null
    }
  }, [tree])

  const allChemins = useMemo(() => tree ? collectChemins(tree.arbre) : [], [tree])
  const toggleExp = (c: string) => setExpanded(p => { const n = new Set(p); n.has(c) ? n.delete(c) : n.add(c); return n })

  // Cocher/décocher un dossier COCHE/DÉCOCHE aussi tous ses sous-dossiers (cascade).
  const toggleSelCascade = (node: IndexedNode) => {
    const sousArbre = collectChemins([node])
    setSelected(prev => {
      const n = new Set(prev)
      const cocher = !prev.has(node.chemin)
      sousArbre.forEach(c => (cocher ? n.add(c) : n.delete(c)))
      return n
    })
  }
  // État visuel d'un dossier : coché si lui + tous ses descendants le sont ; indéterminé si une partie.
  const etatCase = (node: IndexedNode): 'plein' | 'partiel' | 'vide' => {
    const sousArbre = collectChemins([node])
    const coches = sousArbre.filter(c => selected.has(c)).length
    if (coches === 0) return 'vide'
    return coches === sousArbre.length ? 'plein' : 'partiel'
  }

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
    const etat = etatCase(node)
    return (
      <>
        <div className="flex items-center gap-2 px-2 py-1.5 hover:bg-gray-50" style={{ paddingLeft: `${8 + niveau * 18}px` }}>
          <input type="checkbox" checked={etat === 'plein'}
            ref={el => { if (el) el.indeterminate = etat === 'partiel' }}
            onChange={() => toggleSelCascade(node)}
            className="w-4 h-4 accent-amber-600 shrink-0" aria-label={`Sélectionner ${node.nom}${aEnfants ? ' et son contenu' : ''}`} />
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
          <button type="button" onClick={() => charger(true)} disabled={loading}
            title="Rafraîchir les compteurs depuis l'index (conserve la sélection et la position). Ne rescanne PAS le NAS."
            className="p-1 text-gray-400 hover:text-gray-700">
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

      <div ref={scrollRef} className="max-h-72 overflow-auto border border-gray-200 rounded-md bg-white">
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
