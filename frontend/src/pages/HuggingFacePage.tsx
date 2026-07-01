/**
 * HuggingFacePage — Catalogue de modèles (exploration du hub HF)
 * ==============================================================
 * Grille de tuiles de modèles récents (≤ 2 ans) et maintenus, regroupés par catégorie.
 * ⚠️ Sortie Internet : rien n'est chargé au montage. L'utilisateur doit **confirmer**
 * explicitement l'accès (écran d'entrée) — conforme au 100% local / zéro fuite.
 */
import { useState } from 'react'
import { Globe, RefreshCw, Download, Lock, Heart, ExternalLink, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { huggingfaceApi, type HfModel, type HfCatalogParams } from '../api'
import { useToast } from '../components/common/Toast'

const CATEGORIES: { key: NonNullable<HfCatalogParams['category']>; label: string }[] = [
  { key: 'llm', label: 'Raisonnement / LLM' },
  { key: 'embeddings', label: 'Embeddings' },
  { key: 'vision', label: 'Vision / OCR' },
  { key: 'audio', label: 'Audio' },
]

function fmtDate(s: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return isNaN(d.getTime()) ? '—' : d.toLocaleDateString('fr-FR')
}
function fmtNb(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`
  return String(n)
}

export default function HuggingFacePage() {
  const toast = useToast()
  const [loaded, setLoaded] = useState(false)          // consentement d'accès Internet donné
  const [loading, setLoading] = useState(false)
  const [category, setCategory] = useState<NonNullable<HfCatalogParams['category']>>('llm')
  const [maintainedOnly, setMaintainedOnly] = useState(false)
  const [sort, setSort] = useState<NonNullable<HfCatalogParams['sort']>>('downloads')
  const [models, setModels] = useState<HfModel[]>([])

  const charger = async (cat = category, opts?: { sort?: typeof sort; maintainedOnly?: boolean }) => {
    setLoading(true)
    setLoaded(true)
    try {
      const r = await huggingfaceApi.catalog({
        category: cat,
        sort: opts?.sort ?? sort,
        maintained_only: opts?.maintainedOnly ?? maintainedOnly,
        max_age_years: 2,
        maintained_days: 365,
        limit: 60,
      })
      if (r.ok) setModels(r.models)
      else { setModels([]); toast.error(`HuggingFace : ${r.erreur ?? 'injoignable'}`) }
    } catch {
      setModels([])
      toast.error('Catalogue HuggingFace injoignable')
    } finally {
      setLoading(false)
    }
  }

  // ── Écran d'entrée (garde-fou) : consentement avant tout appel réseau ──
  if (!loaded) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="max-w-md text-center bg-white border border-gray-200 rounded-xl p-8 shadow-sm">
          <div className="w-14 h-14 rounded-full bg-yellow-50 flex items-center justify-center mx-auto mb-4">
            <span className="text-3xl">🤗</span>
          </div>
          <h1 className="text-lg font-bold text-gray-800 mb-2">Catalogue HuggingFace</h1>
          <p className="text-sm text-gray-500 mb-4">
            Cette page <strong>interroge HuggingFace (Internet)</strong> pour lister des modèles récents
            et maintenus. Seuls ton <strong>token</strong> et des filtres publics sont envoyés —
            <strong> aucun document, tag, résumé ou nom de fichier</strong>.
          </p>
          <button
            type="button"
            onClick={() => charger()}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-yellow-500 text-white text-sm font-medium rounded-lg hover:bg-yellow-600"
          >
            <Globe size={16} /> Charger le catalogue
          </button>
          <p className="text-[11px] text-gray-400 mt-3">100% local le reste du temps · action confirmée</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* En-tête + rappel réseau */}
      <div className="px-4 py-3 border-b border-gray-200 bg-white">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h1 className="text-base font-bold text-gray-800 flex items-center gap-2">
            <span>🤗</span> Catalogue HuggingFace
            <span className="text-[10px] font-normal px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-600 flex items-center gap-1">
              <Globe size={10} /> en ligne
            </span>
          </h1>
          <div className="flex items-center gap-2">
            <select
              value={sort}
              onChange={e => { const s = e.target.value as typeof sort; setSort(s); charger(category, { sort: s }) }}
              title="Trier"
              className="text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white"
            >
              <option value="downloads">Plus téléchargés</option>
              <option value="likes">Plus aimés</option>
              <option value="lastModified">Récemment mis à jour</option>
            </select>
            <label className="text-xs text-gray-600 flex items-center gap-1">
              <input type="checkbox" checked={maintainedOnly}
                onChange={e => { setMaintainedOnly(e.target.checked); charger(category, { maintainedOnly: e.target.checked }) }} />
              Maintenus seulement
            </label>
            <button type="button" onClick={() => charger()} disabled={loading}
              title="Recharger (appel réseau)"
              className="flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50">
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Recharger
            </button>
          </div>
        </div>

        {/* Onglets catégories (= regroupement par fonction) */}
        <div className="flex gap-1.5 mt-3 flex-wrap">
          {CATEGORIES.map(c => (
            <button key={c.key} type="button"
              onClick={() => { setCategory(c.key); charger(c.key) }}
              className={clsx('text-xs px-3 py-1.5 rounded-full border transition-colors',
                category === c.key ? 'bg-yellow-500 text-white border-yellow-500' : 'border-gray-200 text-gray-600 hover:bg-gray-50')}>
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* Grille de tuiles */}
      <div className="flex-1 overflow-y-auto p-4 bg-gray-50">
        {loading ? (
          <div className="flex justify-center py-16"><Loader2 size={22} className="animate-spin text-gray-400" /></div>
        ) : models.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-16">Aucun modèle pour ces critères.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {models.map(m => (
              <div key={m.id} className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2 hover:border-yellow-300 transition-colors">
                <div className="flex items-start justify-between gap-2">
                  <a href={`https://huggingface.co/${m.id}`} target="_blank" rel="noopener noreferrer"
                    className="text-sm font-medium text-gray-800 hover:text-yellow-600 break-all leading-tight flex items-start gap-1">
                    {m.id}
                    <ExternalLink size={11} className="text-gray-300 shrink-0 mt-0.5" />
                  </a>
                  {m.uncensored ? (
                    <span title="Sans censure (heuristique)" className="text-sm shrink-0">😈</span>
                  ) : (
                    <span title="Standard / officiel" className="text-[9px] px-1 py-0.5 rounded bg-blue-50 text-blue-600 shrink-0">officiel</span>
                  )}
                </div>

                <div className="flex items-center gap-1.5 flex-wrap">
                  {m.categorie && <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{m.categorie}</span>}
                  {m.gguf && <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-50 text-green-700" title="Installable via Ollama">GGUF</span>}
                  {m.gated && <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-50 text-orange-600 flex items-center gap-0.5" title="Accès restreint (conditions à accepter sur HF)"><Lock size={9} /> gated</span>}
                  {m.maintained && <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700">🟢 maintenu</span>}
                </div>

                <div className="text-[11px] text-gray-400 flex items-center gap-3 flex-wrap">
                  <span>En ligne : {fmtDate(m.created_at)}</span>
                  <span>MAJ : {fmtDate(m.last_modified)}</span>
                </div>
                <div className="text-[11px] text-gray-400 flex items-center gap-3">
                  <span className="flex items-center gap-0.5"><Download size={11} /> {fmtNb(m.downloads)}</span>
                  <span className="flex items-center gap-0.5"><Heart size={11} /> {fmtNb(m.likes)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
