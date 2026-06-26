/**
 * IndexedSourcesSummary — Récap des dossiers RÉELLEMENT indexés, par source
 * =========================================================================
 * Remplace l'ancienne section « Indexations actives » (qui ne montrait que les
 * dossiers surveillés auto-scan). Ici on liste, pour chaque source, sa racine +
 * le nombre de documents indexés, avec un bouton « Gérer » qui ouvre l'arbre
 * (cases à cocher + retirer de l'index) — sans avoir à passer par « Indexés ».
 */
import { useCallback, useEffect, useState } from 'react'
import { Database, FolderOpen, Settings2, Loader2, RefreshCw } from 'lucide-react'
import { sourcesApi, type Source } from '../../api'
import IndexedFolders from './IndexedFolders'

interface Summary { racine: string; nb: number }

export default function IndexedSourcesSummary() {
  const [sources, setSources] = useState<Source[]>([])
  const [summ, setSumm] = useState<Record<string, Summary | null>>({})
  const [loading, setLoading] = useState(true)
  const [manage, setManage] = useState<Source | null>(null)

  const chargerSource = useCallback(async (s: Source): Promise<Summary | null> => {
    try {
      const t = await sourcesApi.indexed(s.id)
      return { racine: t.racine, nb: t.nb_documents }
    } catch { return null }
  }, [])

  const chargerTout = useCallback(async () => {
    setLoading(true)
    try {
      const srcs = await sourcesApi.list()
      setSources(srcs)
      const entries = await Promise.all(srcs.map(async s => [s.id, await chargerSource(s)] as const))
      setSumm(Object.fromEntries(entries))
    } catch { /* silencieux */ } finally { setLoading(false) }
  }, [chargerSource])

  useEffect(() => { chargerTout() }, [chargerTout])

  const fermerGestion = async () => {
    const s = manage
    setManage(null)
    if (s) setSumm(prev => ({ ...prev, [s.id]: prev[s.id] ?? null }))  // placeholder
    if (s) { const r = await chargerSource(s); setSumm(prev => ({ ...prev, [s.id]: r })) }
  }

  // Sources ayant au moins un document indexé
  const indexees = sources.filter(s => (summ[s.id]?.nb ?? 0) > 0)

  return (
    <div>
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        {loading ? (
          <p className="text-xs text-gray-400 px-4 py-6 flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Chargement…
          </p>
        ) : indexees.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-gray-300">
            <FolderOpen size={32} strokeWidth={1} />
            <p className="text-sm">Aucun dossier indexé pour l'instant</p>
            <p className="text-xs">Indexe un dossier depuis « Sources de fichiers » ci-dessus</p>
          </div>
        ) : (
          indexees.map((s, i) => {
            const info = summ[s.id]!
            return (
              <div key={s.id} className={`flex items-center gap-3 px-4 py-3 ${i > 0 ? 'border-t border-gray-100' : ''}`}>
                <Database size={16} className="text-blue-500 shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{s.libelle}</p>
                  <p className="text-xs text-gray-400 truncate font-mono">{info.racine}</p>
                </div>
                <span className="text-xs text-gray-500 shrink-0">{info.nb} doc.</span>
                <button
                  onClick={() => setManage(manage?.id === s.id ? null : s)}
                  title="Gérer les dossiers indexés (retirer de l'index)"
                  className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 shrink-0"
                >
                  <Settings2 size={13} /> Gérer
                </button>
              </div>
            )
          })
        )}
      </div>

      {!loading && (
        <button onClick={chargerTout} className="text-xs text-gray-400 hover:text-gray-600 mt-2 flex items-center gap-1">
          <RefreshCw size={11} /> Rafraîchir
        </button>
      )}

      {/* Arbre de gestion (réutilise IndexedFolders : cases à cocher + désindexer) */}
      {manage && (
        <div className="mt-3">
          <IndexedFolders source={manage} onClose={fermerGestion} />
        </div>
      )}
    </div>
  )
}
