/**
 * HuggingFacePage — Catalogue de modèles (exploration du hub HF)
 * ==============================================================
 * Grille de tuiles de modèles récents (≤ 2 ans) et maintenus, regroupés par catégorie.
 * ⚠️ Sortie Internet : rien n'est chargé au montage. L'utilisateur doit **confirmer**
 * explicitement l'accès (écran d'entrée) — conforme au 100% local / zéro fuite.
 */
import { useEffect, useState } from 'react'
import { Globe, RefreshCw, Download, Lock, Heart, ExternalLink, Loader2, X, Copy, Check, CheckCircle2 } from 'lucide-react'
import { clsx } from 'clsx'
import { huggingfaceApi, systemApi, type HfModel, type HfModelDetail, type HfCatalogParams } from '../api'
import { useToast } from '../components/common/Toast'

const CATEGORIES: { key: NonNullable<HfCatalogParams['category']>; label: string; desc: string }[] = [
  { key: 'llm', label: 'Raisonnement / LLM', desc: 'Modèles de génération de texte : rapports, résumés, classification, chat, raisonnement.' },
  { key: 'embeddings', label: 'Embeddings', desc: 'Vectorisation du texte pour la recherche sémantique de la GED (similarité de sens).' },
  { key: 'vision', label: 'Vision / OCR', desc: 'Analyse d\'images : OCR (lire un scan), description d\'image, questions sur une image.' },
  { key: 'audio', label: 'Audio', desc: 'Transcription audio → texte (speech-to-text), ex. pour des enregistrements.' },
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
  const [censure, setCensure] = useState<'all' | 'officiel' | 'uncensored'>('all')  // filtre officiel/😈
  const [installedOnly, setInstalledOnly] = useState(false)  // filtre « installé »
  const [models, setModels] = useState<HfModel[]>([])
  const [installes, setInstalles] = useState<string[]>([])  // modèles Ollama déjà installés (local)

  // Liste des modèles installés (appel LOCAL Ollama, aucun réseau) — pour le tag « installé ».
  const rafraichirInstalles = () =>
    systemApi.models().then(r => setInstalles(r.models.map(m => m.name))).catch(() => {})
  useEffect(() => { rafraichirInstalles() }, [])

  // Un modèle HF est « installé » s'il correspond à un modèle Ollama présent (notamment pull
  // via `hf.co/<id>`), en comparant sans le tag/quant. Heuristique volontairement prudente.
  const estInstalle = (id: string): boolean => {
    const ref = `hf.co/${id}`.toLowerCase()
    const full = id.toLowerCase()          // org/model
    const seg = (id.split('/').pop() || '').toLowerCase()  // model
    return installes.some(n => {
      const base = n.toLowerCase().split(':')[0]  // retire :quant / :latest
      return base === ref || base === full || base.endsWith('/' + seg) || base === seg
    })
  }
  // Détail (modal au clic sur une carte)
  const [selected, setSelected] = useState<HfModel | null>(null)
  const [detail, setDetail] = useState<HfModelDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [confirmInstall, setConfirmInstall] = useState(false)
  const [installStatus, setInstallStatus] = useState<string | null>(null)
  const [installPct, setInstallPct] = useState<number | null>(null)  // % barre (null = indéterminé)

  const ouvrirDetail = async (m: HfModel) => {
    setSelected(m); setDetail(null); setDetailLoading(true); setCopied(false); setConfirmInstall(false); setInstallStatus(null)
    try {
      setDetail(await huggingfaceApi.model(m.id))
    } catch {
      setDetail({ ok: false, id: m.id, erreur: 'injoignable' })
    } finally {
      setDetailLoading(false)
    }
  }
  const fermerDetail = () => { setSelected(null); setDetail(null); setInstallStatus(null) }

  const cmdPowershell = (id: string) => `ollama pull hf.co/${id}`
  const copierCmd = (id: string) => {
    navigator.clipboard.writeText(cmdPowershell(id)).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000) })
  }

  // Installation « dans l'infra » = ollama pull hf.co/<id> (téléchargement Internet → confirmé).
  const installer = async (id: string) => {
    setConfirmInstall(false)
    setInstallStatus('Démarrage…')
    setInstallPct(null)
    try {
      await systemApi.pullModel(`hf.co/${id}`, p => {
        setInstallStatus(p.status ?? 'Téléchargement…')
        setInstallPct(p.total ? Math.round((p.completed ?? 0) / p.total * 100) : null)
      })
      setInstallStatus(null); setInstallPct(null)
      await rafraichirInstalles()   // met à jour le tag « installé »
      toast.success(`« ${id} » installé — dispo dans Paramètres → Modèles`)
    } catch {
      setInstallStatus(null); setInstallPct(null)
      toast.error('Installation échouée (modèle non-GGUF ou gated ?)')
    }
  }

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

  // Filtres client (officiel/😈 + installé), sur les modèles déjà chargés.
  const visibles = models.filter(m =>
    (censure === 'all' || (censure === 'uncensored' ? m.uncensored : !m.uncensored)) &&
    (!installedOnly || estInstalle(m.id)),
  )

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

        {/* Onglets catégories (= regroupement par fonction) + filtre officiel/😈 */}
        <div className="flex gap-1.5 mt-3 flex-wrap items-center">
          {CATEGORIES.map(c => (
            <button key={c.key} type="button" title={c.desc}
              onClick={() => { setCategory(c.key); charger(c.key) }}
              className={clsx('text-xs px-3 py-1.5 rounded-full border transition-colors',
                category === c.key ? 'bg-yellow-500 text-white border-yellow-500' : 'border-gray-200 text-gray-600 hover:bg-gray-50')}>
              {c.label}
            </button>
          ))}
          <span className="w-px h-5 bg-gray-200 mx-1" />
          {([
            { key: 'all', label: 'Tous' },
            { key: 'officiel', label: 'officiel' },
            { key: 'uncensored', label: '😈' },
          ] as const).map(f => (
            <button key={f.key} type="button" onClick={() => setCensure(f.key)}
              title={f.key === 'uncensored' ? 'Sans censure (heuristique)' : f.key === 'officiel' ? 'Standard / officiel' : 'Tous'}
              className={clsx('text-xs px-3 py-1.5 rounded-full border transition-colors',
                censure === f.key ? 'bg-gray-800 text-white border-gray-800' : 'border-gray-200 text-gray-600 hover:bg-gray-50')}>
              {f.label}
            </button>
          ))}
          <button type="button" onClick={() => setInstalledOnly(v => !v)}
            title="N'afficher que les modèles déjà installés dans Ollama"
            className={clsx('text-xs px-3 py-1.5 rounded-full border transition-colors flex items-center gap-1',
              installedOnly ? 'bg-green-600 text-white border-green-600' : 'border-gray-200 text-gray-600 hover:bg-gray-50')}>
            <CheckCircle2 size={11} /> installé
          </button>
        </div>
      </div>

      {/* Grille de tuiles (filtrée officiel/😈) */}
      <div className="flex-1 overflow-y-auto p-4 bg-gray-50">
        {loading ? (
          <div className="flex justify-center py-16"><Loader2 size={22} className="animate-spin text-gray-400" /></div>
        ) : visibles.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-16">Aucun modèle pour ces critères.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {visibles.map(m => (
              <div key={m.id} onClick={() => ouvrirDetail(m)}
                className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2 hover:border-yellow-300 hover:shadow-sm cursor-pointer transition-all">
                <div className="flex items-start justify-between gap-2">
                  <a href={`https://huggingface.co/${m.id}`} target="_blank" rel="noopener noreferrer"
                    onClick={e => e.stopPropagation()}
                    className="text-sm font-medium text-gray-800 hover:text-yellow-600 break-all leading-tight flex items-start gap-1">
                    {m.id}
                    <ExternalLink size={11} className="text-gray-300 shrink-0 mt-0.5" />
                  </a>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {m.uncensored ? (
                      <span title="Sans censure (heuristique)" className="text-sm">😈</span>
                    ) : (
                      <span title="Standard / officiel" className="text-[9px] px-1 py-0.5 rounded bg-blue-50 text-blue-600">officiel</span>
                    )}
                    <span title="Voir le détail / installer"><Download size={14} className="text-gray-300" /></span>
                  </div>
                </div>

                <div className="flex items-center gap-1.5 flex-wrap">
                  {estInstalle(m.id) && <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-600 text-white flex items-center gap-0.5" title="Déjà présent dans ton Ollama"><CheckCircle2 size={9} /> installé</span>}
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

      {/* Modal détail : résumé + installation */}
      {selected && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={fermerDetail}>
          <div className="bg-white rounded-xl shadow-xl max-w-lg w-full max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3 p-4 border-b border-gray-100">
              <div className="min-w-0">
                <a href={`https://huggingface.co/${selected.id}`} target="_blank" rel="noopener noreferrer"
                  className="font-semibold text-gray-800 break-all hover:text-yellow-600 flex items-center gap-1">
                  {selected.id} <ExternalLink size={12} className="text-gray-300 shrink-0" />
                </a>
                <div className="flex items-center gap-1.5 mt-1 flex-wrap text-[10px]">
                  {selected.categorie && <span className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{selected.categorie}</span>}
                  {selected.uncensored
                    ? <span className="px-1.5 py-0.5 rounded bg-purple-50 text-purple-600">😈 sans censure</span>
                    : <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-600">officiel</span>}
                  {detail?.gguf && <span className="px-1.5 py-0.5 rounded bg-green-50 text-green-700">GGUF</span>}
                  {detail?.gated && <span className="px-1.5 py-0.5 rounded bg-orange-50 text-orange-600">🔒 gated</span>}
                </div>
              </div>
              <button type="button" onClick={fermerDetail} title="Fermer" className="text-gray-400 hover:text-gray-600 shrink-0"><X size={18} /></button>
            </div>

            <div className="p-4 space-y-3">
              {/* Résumé « ce que fait le modèle » */}
              <div>
                <p className="text-xs font-semibold text-gray-500 uppercase mb-1 flex items-center gap-2">
                  Ce que fait ce modèle
                  {detail?.resume_ia && (
                    <span className="text-[9px] font-normal px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600 normal-case" title="Résumé traduit/généré par ton IA locale (Ollama)">🤖 résumé IA locale</span>
                  )}
                </p>
                {detailLoading ? (
                  <div className="flex items-center gap-2 text-sm text-gray-400"><Loader2 size={14} className="animate-spin" /> Résumé par l'IA locale…</div>
                ) : detail?.resume ? (
                  <p className="text-sm text-gray-700 leading-relaxed">{detail.resume}</p>
                ) : (
                  <p className="text-sm text-gray-400 italic">Pas de résumé disponible.{selected.categorie ? ` Catégorie : ${selected.categorie}.` : ''}</p>
                )}
              </div>

              {/* Infos */}
              <div className="flex items-center gap-4 text-xs text-gray-500 flex-wrap">
                <span className="flex items-center gap-1"><Download size={12} /> {fmtNb(selected.downloads)}</span>
                <span className="flex items-center gap-1"><Heart size={12} /> {fmtNb(selected.likes)}</span>
                {detail?.license && <span>Licence : {detail.license}</span>}
                <span>MAJ {fmtDate(selected.last_modified)}</span>
              </div>

              {/* Installation */}
              <div className="border-t border-gray-100 pt-3">
                <p className="text-xs font-semibold text-gray-500 uppercase mb-2 flex items-center gap-1"><Download size={12} /> Installer dans mon infra</p>

                {/* Commande PowerShell prête à copier */}
                <div className="flex items-center gap-2 bg-gray-900 rounded-md px-3 py-2">
                  <code className="text-xs text-green-300 flex-1 break-all">{cmdPowershell(selected.id)}</code>
                  <button type="button" onClick={() => copierCmd(selected.id)} title="Copier"
                    className="text-gray-300 hover:text-white shrink-0">
                    {copied ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
                  </button>
                </div>
                <p className="text-[10px] text-gray-400 mt-1">À coller dans PowerShell (Ollama). Pour une quantization précise : ajoute <code>:Q4_K_M</code>.</p>

                {/* Bouton installer (via l'app) */}
                <div className="mt-3">
                  {estInstalle(selected.id) ? (
                    <div className="flex items-center gap-1.5 text-sm text-green-600 font-medium"><CheckCircle2 size={15} /> Déjà installé dans ton Ollama</div>
                  ) : installStatus ? (
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-2 text-xs text-blue-600">
                        <Loader2 size={13} className="animate-spin shrink-0" />
                        <span className="flex-1 truncate">{installStatus}</span>
                        {installPct != null && <span className="tabular-nums shrink-0">{installPct}%</span>}
                      </div>
                      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                        <div className={clsx('h-full bg-yellow-500 transition-all', installPct == null && 'w-1/3 animate-pulse')}
                          style={installPct != null ? { width: `${installPct}%` } : undefined} />
                      </div>
                    </div>
                  ) : confirmInstall ? (
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs text-gray-600">⚠️ Télécharge depuis Internet. Confirmer ?</span>
                      <button type="button" onClick={() => installer(selected.id)} className="text-xs px-3 py-1.5 bg-yellow-500 text-white rounded-md hover:bg-yellow-600">Confirmer</button>
                      <button type="button" onClick={() => setConfirmInstall(false)} className="text-xs px-3 py-1.5 border border-gray-200 text-gray-500 rounded-md">Annuler</button>
                    </div>
                  ) : (
                    <button type="button" onClick={() => setConfirmInstall(true)}
                      className="flex items-center gap-1.5 text-sm px-3 py-2 bg-yellow-500 text-white rounded-lg hover:bg-yellow-600">
                      <Download size={14} /> Installer dans l'infra (Ollama)
                    </button>
                  )}
                  {detail && !detail.gguf && !installStatus && !confirmInstall && !estInstalle(selected.id) && (
                    <p className="text-[10px] text-orange-500 mt-1">⚠️ Modèle non-GGUF : le pull direct peut échouer. Préfère un dépôt GGUF ou la commande manuelle.</p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
