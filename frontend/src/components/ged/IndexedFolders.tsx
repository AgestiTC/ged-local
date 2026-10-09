/**
 * IndexedFolders — Arbre des dossiers RÉELLEMENT indexés d'une source.
 * Dossier parent déplié, sous-dossiers pliés. Cases à cocher + tout cocher/décocher
 * pour RETIRER des dossiers de l'index (désindexer) — ne touche pas aux fichiers du NAS.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Folder, FolderOpen, ChevronRight, ChevronDown, Loader2, Trash2, RefreshCw, X } from 'lucide-react'
import { sourcesApi, type Source, type IndexedNode, type IndexedTree, type SyncDossier } from '../../api'
import { useToast } from '../common/Toast'
import {
  RepereSurveille, couleurDossier, libelleFrequence, phraseFrequence, rafraichirDossiersSurveilles,
  useDossiersSurveilles,
} from '../../hooks/useDossiersSurveilles'

// Fréquences proposées pour un dossier (la source peut en avoir une autre : elle reste affichée).
const FREQUENCES = [60, 360, 1440]

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
  // Surveillance automatique : réglage par dossier (clé = chemin du nœud), et défaut de la source.
  const [sync, setSync] = useState<{ defaut: number; parChemin: Record<string, SyncDossier> }>({ defaut: 0, parChemin: {} })
  const { surveillance } = useDossiersSurveilles()

  const chargerSync = useCallback(async () => {
    try {
      const r = await sourcesApi.syncDossiers(source.id)
      setSync({ defaut: r.defaut_minutes, parChemin: Object.fromEntries(r.dossiers.map(d => [d.chemin_arbre, d])) })
    } catch { /* le réglage est un plus : l'arbre reste utilisable sans lui */ }
  }, [source.id])

  useEffect(() => { void chargerSync() }, [chargerSync])

  // `minutes` : 0 = ne plus surveiller ; null = suivre la fréquence de la source.
  const reglerSurveillance = async (d: SyncDossier, minutes: number | null) => {
    try {
      await sourcesApi.reglerSyncDossier(source.id, d.cle, minutes)
      await Promise.all([chargerSync(), rafraichirDossiersSurveilles()])
    } catch { toast.error('Réglage de la surveillance impossible') }
  }

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
    const reglage = sync.parChemin[node.chemin]          // défini pour les dossiers réglables
    const surv = surveillance(node.chemin)               // ce dossier, ou un parent, est surveillé
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
          {aEnfants && ouvert
            ? <FolderOpen size={14} className={`${couleurDossier(!!surv)} shrink-0`} />
            : <Folder size={14} className={`${couleurDossier(!!surv)} shrink-0`} />}
          <span className="text-sm truncate flex-1 flex items-center gap-1.5 min-w-0">
            <span className="truncate">{node.nom}</span>
            {surv && <RepereSurveille minutes={surv.minutes} direct={surv.direct} />}
          </span>
          {reglage && (
            <span className="flex items-center gap-1.5 shrink-0 text-xs text-gray-600">
              <label className="flex items-center gap-1 cursor-pointer"
                title="Matothèque compare seule ce dossier au NAS, à la fréquence choisie. Décoché : il n'est synchronisé qu'à la demande (clic droit dans « Parcourir »).">
                <input type="checkbox" checked={reglage.effectif_minutes > 0}
                  onChange={e => reglerSurveillance(reglage, e.target.checked ? (sync.defaut > 0 ? null : 60) : 0)}
                  className="w-3.5 h-3.5 accent-emerald-600" />
                Surveiller
              </label>
              {reglage.effectif_minutes > 0 && (
                <select aria-label={`Fréquence de surveillance de ${node.nom}`}
                  value={reglage.minutes === null ? 'source' : String(reglage.minutes)}
                  onChange={e => reglerSurveillance(reglage, e.target.value === 'source' ? null : Number(e.target.value))}
                  className="text-xs border border-gray-200 rounded px-1 py-0.5 bg-white text-gray-700">
                  {sync.defaut > 0 && <option value="source">comme la source ({libelleFrequence(sync.defaut)})</option>}
                  {[...new Set([...FREQUENCES, ...(reglage.minutes ? [reglage.minutes] : [])])].sort((a, b) => a - b)
                    .map(m => <option key={m} value={m}>{phraseFrequence(m)}</option>)}
                </select>
              )}
            </span>
          )}
          <span className="text-xs text-gray-400 shrink-0 w-10 text-right">{node.nb}</span>
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

      {Object.keys(sync.parChemin).length > 0 && (
        <p className="text-xs text-gray-500 mb-1.5 flex items-center gap-1.5 flex-wrap">
          <RepereSurveille minutes={sync.defaut || 60} />
          <span>
            <strong>Surveiller</strong> un dossier : Matothèque le compare seule au NAS à la fréquence choisie.
            Les autres ne sont synchronisés qu'à la demande. La case de gauche sert à <strong>retirer de l'index</strong>.
          </span>
        </p>
      )}

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
