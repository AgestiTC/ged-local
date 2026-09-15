/**
 * DiagnosticIA — « mon IA locale est-elle bien réglée pour ma machine ? »
 *
 * Trois étages, du plus sûr au plus libre :
 *  1. **Constats** calculés par le backend à partir de l'API d'Ollama (règles déterministes :
 *     modèle absent pour un usage, import sans template de chat, quantisation trop lourde,
 *     débordement de VRAM…). Aucune sortie Internet.
 *  2. **Synthèse** rédigée par l'IA LOCALE à partir de ces constats — sur demande, en streaming.
 *  3. **Prompt à copier** dans une IA web, pour ce qu'on ne peut pas savoir hors ligne (modèles
 *     plus récents, nouvelle version d'Ollama). L'application n'envoie rien : l'utilisateur copie.
 *
 * Ollama n'expose ni la VRAM ni la RAM : on les demande, et on les garde dans le navigateur.
 */
import { useRef, useState } from 'react'
import { AlertTriangle, Bot, Copy, Info, Lightbulb, ShieldCheck, Square, Stethoscope, XCircle } from 'lucide-react'
import { clsx } from 'clsx'
import { chatApi, systemApi, type ConstatIA, type DiagnosticIA as Diagnostic, type NiveauConstat } from '../../api'
import { useToast } from '../common/Toast'
import { copierTexte } from '../../utils/clipboard'

const CLE_MATERIEL = 'mtq_diagnostic_materiel'

type Materiel = { gpu: string; vram: string; ram: string }

function lireMateriel(): Materiel {
  try {
    const m = JSON.parse(localStorage.getItem(CLE_MATERIEL) || '{}')
    return { gpu: m.gpu ?? '', vram: m.vram ?? '16', ram: m.ram ?? '' }
  } catch {
    return { gpu: '', vram: '16', ram: '' }
  }
}

const STYLE_NIVEAU: Record<NiveauConstat, { label: string; bord: string; badge: string; Icon: typeof Info }> = {
  critique:  { label: 'Critique',  bord: 'border-l-red-500',   badge: 'bg-red-50 text-red-700',       Icon: XCircle },
  important: { label: 'Important', bord: 'border-l-amber-500', badge: 'bg-amber-50 text-amber-700',   Icon: AlertTriangle },
  conseil:   { label: 'Conseil',   bord: 'border-l-blue-400',  badge: 'bg-blue-50 text-blue-700',     Icon: Lightbulb },
  info:      { label: 'Info',      bord: 'border-l-gray-300',  badge: 'bg-gray-100 text-gray-600',    Icon: Info },
}

function CarteConstat({ c }: { c: ConstatIA }) {
  const s = STYLE_NIVEAU[c.niveau]
  return (
    <li className={clsx('border border-gray-100 border-l-4 rounded-md px-3 py-2 bg-white', s.bord)}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={clsx('inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded', s.badge)}>
          <s.Icon size={11} /> {s.label}
        </span>
        <span className="text-sm font-medium text-gray-800">{c.titre}</span>
      </div>
      <p className="text-xs text-gray-600 mt-1">{c.detail}</p>
      {c.action && <p className="text-xs text-gray-800 mt-1"><span className="text-gray-400">→</span> {c.action}</p>}
    </li>
  )
}

export default function DiagnosticIA() {
  const toast = useToast()
  const [materiel, setMateriel] = useState<Materiel>(lireMateriel)
  const [diag, setDiag] = useState<Diagnostic | null>(null)
  const [analyse, setAnalyse] = useState(false)
  const [erreur, setErreur] = useState('')

  const [synthese, setSynthese] = useState('')
  const [redaction, setRedaction] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const changer = (champ: keyof Materiel, valeur: string) => {
    const suivant = { ...materiel, [champ]: valeur }
    setMateriel(suivant)
    try { localStorage.setItem(CLE_MATERIEL, JSON.stringify(suivant)) } catch { /* navigation privée */ }
  }

  const vram = parseFloat(materiel.vram.replace(',', '.'))
  const ram = parseFloat(materiel.ram.replace(',', '.'))
  const vramValide = Number.isFinite(vram) && vram > 0

  const analyser = async () => {
    if (!vramValide) return
    abortRef.current?.abort()
    setAnalyse(true); setErreur(''); setSynthese('')
    try {
      setDiag(await systemApi.diagnosticIA({
        vram_go: vram,
        ram_go: Number.isFinite(ram) && ram > 0 ? ram : undefined,
        gpu: materiel.gpu.trim() || undefined,
      }))
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErreur(detail || 'Analyse impossible (Ollama injoignable ?).')
    } finally {
      setAnalyse(false)
    }
  }

  const rediger = async () => {
    if (!diag || redaction) return
    setSynthese(''); setRedaction(true)
    const ac = new AbortController(); abortRef.current = ac
    try {
      // Modèle des RAPPORTS : c'est celui choisi pour la qualité d'écriture en français.
      await chatApi.stream(
        [{ role: 'system', content: diag.prompt_local.systeme }, { role: 'user', content: diag.prompt_local.utilisateur }],
        diag.usages.rapport, false, chunk => setSynthese(t => t + chunk), ac.signal,
      )
    } catch {
      if (!ac.signal.aborted) setSynthese(t => t || '⚠️ IA locale injoignable.')
    } finally {
      setRedaction(false); abortRef.current = null
    }
  }

  const copierPrompt = () => {
    if (!diag) return
    copierTexte(diag.prompt_internet)
      .then(() => toast.success('Prompt copié — colle-le dans une IA web (Claude, ChatGPT, Perplexity).'))
      .catch(() => toast.error('Copie impossible — sélectionne le texte à la main.'))
  }

  const compte = (n: NiveauConstat) => diag?.constats.filter(c => c.niveau === n).length ?? 0
  const charges = new Map(diag?.charges.map(c => [c.nom, c]) ?? [])

  return (
    <div className="px-4 py-3">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-medium text-gray-700">Analyse IA de l'installation</p>
            <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700">
              <ShieldCheck size={11} /> 100 % local
            </span>
          </div>
          <p className="text-xs text-gray-400 mt-0.5 max-w-xl">
            Passe en revue les modèles Ollama face à ta machine : usages pointant vers un modèle absent,
            imports sans template de chat, quantisations trop lourdes, débordements de VRAM. N'interroge
            que <strong>Ollama</strong>. Pour les nouveautés, un <strong>prompt à copier</strong> dans une IA web est fourni.
          </p>
        </div>
        <button type="button" onClick={analyser} disabled={analyse || !vramValide}
          className="flex items-center gap-1.5 shrink-0 px-3 py-2 text-sm border border-blue-200 text-blue-600 rounded-lg hover:bg-blue-50 disabled:opacity-40 transition-colors">
          <Stethoscope size={14} className={analyse ? 'animate-pulse' : ''} />
          {analyse ? 'Analyse…' : 'Analyser'}
        </button>
      </div>

      {/* Matériel : Ollama ne l'expose pas. Gardé dans ce navigateur uniquement. */}
      <div className="flex flex-wrap items-end gap-3 mt-3">
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          GPU
          <input type="text" value={materiel.gpu} onChange={e => changer('gpu', e.target.value)}
            placeholder="ex. RTX 4080 SUPER" maxLength={80}
            className="w-44 text-sm border border-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          VRAM (Go)
          <input type="number" min={1} step={1} value={materiel.vram} onChange={e => changer('vram', e.target.value)}
            className={clsx('w-24 text-sm border rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400',
              vramValide ? 'border-gray-200' : 'border-red-300')} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          RAM (Go, facultatif)
          <input type="number" min={1} step={1} value={materiel.ram} onChange={e => changer('ram', e.target.value)}
            className="w-28 text-sm border border-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400" />
        </label>
        <span className="text-[10px] text-gray-400 pb-2">Mémorisé dans ce navigateur.</span>
      </div>

      {erreur && <p className="mt-3 text-xs text-red-600">{erreur}</p>}

      {diag && (
        <div className="mt-4 space-y-4">
          {/* Bilan */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {(['critique', 'important', 'conseil', 'info'] as NiveauConstat[]).map(n => (
              <span key={n} className={clsx('px-2 py-0.5 rounded-full', STYLE_NIVEAU[n].badge, compte(n) === 0 && 'opacity-50')}>
                {compte(n)} {STYLE_NIVEAU[n].label.toLowerCase()}
              </span>
            ))}
            <span className="text-gray-400">
              · Ollama {diag.ollama_version || '?'} · {diag.modeles.length} modèle(s) · {diag.charges.length} chargé(s)
            </span>
          </div>

          {diag.erreurs.length > 0 && (
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-100 rounded-md px-2 py-1.5">
              Analyse partielle : {diag.erreurs.join(' · ')}
            </p>
          )}

          {diag.constats.length === 0
            ? <p className="text-sm text-emerald-700">Aucun problème détecté.</p>
            : <ul className="space-y-2">{diag.constats.map((c, i) => <CarteConstat key={i} c={c} />)}</ul>}

          {/* Détail des modèles */}
          <details>
            <summary className="text-xs font-medium text-gray-600 cursor-pointer hover:text-blue-600 select-none">
              Modèles analysés ({diag.modeles.length})
            </summary>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[720px] text-xs border-collapse">
                <thead>
                  <tr className="text-left text-gray-500 border-b border-gray-200">
                    {['Modèle', 'Taille', 'Quant', 'Architecture', 'Capacités', 'Template', 'En mémoire'].map(h => (
                      <th key={h} className="py-1.5 px-2 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {diag.modeles.map(m => {
                    const c = charges.get(m.nom)
                    return (
                      <tr key={m.nom} className="border-b border-gray-50 align-top">
                        <td className="py-1.5 px-2 font-medium text-gray-700 break-all">{m.nom}</td>
                        <td className="py-1.5 px-2 text-gray-600 whitespace-nowrap">{m.taille_go} Go</td>
                        <td className="py-1.5 px-2 text-gray-600">{m.quantisation || '—'}</td>
                        <td className="py-1.5 px-2 text-gray-600 whitespace-nowrap">
                          {m.moe ? `MoE ${m.experts_actifs}/${m.experts}` : 'dense'}{m.parametres && ` · ${m.parametres}`}
                        </td>
                        <td className="py-1.5 px-2 text-gray-600">{m.capacites.join(', ') || '—'}</td>
                        <td className="py-1.5 px-2">
                          {!m.analyse_complete ? <span className="text-gray-400">?</span>
                            : m.capacites.includes('embedding') ? <span className="text-gray-400">—</span>
                            : m.template_ok ? <span className="text-emerald-600">OK</span>
                            : <span className="text-amber-600">absent</span>}
                        </td>
                        <td className="py-1.5 px-2 text-gray-600 whitespace-nowrap">
                          {c ? `${c.part_gpu} % GPU · ctx ${c.contexte}${c.permanent ? ' · permanent' : ''}` : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </details>

          {/* Synthèse rédigée par l'IA locale */}
          <div className="border border-gray-200 rounded-lg p-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <p className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
                <Bot size={15} className="text-violet-500" /> Recommandations de l'IA locale
              </p>
              {redaction ? (
                <button type="button" onClick={() => abortRef.current?.abort()}
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-gray-700 text-white hover:bg-gray-800">
                  <Square size={12} /> Stop
                </button>
              ) : (
                <button type="button" onClick={rediger}
                  className="text-xs px-2 py-1 rounded-md border border-violet-200 text-violet-600 hover:bg-violet-50">
                  {synthese ? 'Rédiger à nouveau' : 'Rédiger'}
                </button>
              )}
            </div>
            <p className="text-[10px] text-gray-400 mt-0.5">
              Modèle : {diag.usages.rapport || 'défaut'} · s'appuie uniquement sur les constats ci-dessus.
            </p>
            {(synthese || redaction) && (
              <div className="mt-2 text-sm text-gray-800 whitespace-pre-wrap break-words">
                {synthese || <span className="text-gray-400">…</span>}
              </div>
            )}
          </div>

          {/* Prompt pour une IA internet */}
          <div className="border border-gray-200 rounded-lg p-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <p className="text-sm font-medium text-gray-700">Prompt pour une IA internet</p>
              <button type="button" onClick={copierPrompt}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-blue-200 text-blue-600 hover:bg-blue-50">
                <Copy size={12} /> Copier
              </button>
            </div>
            <p className="text-[10px] text-gray-400 mt-0.5">
              Rien n'est envoyé par Matothèque. Le prompt ne contient que ton matériel, les noms de modèles
              et leurs usages — aucun document, tag ni chemin.
            </p>
            <textarea readOnly value={diag.prompt_internet} rows={8}
              className="mt-2 w-full resize-y text-xs font-mono border border-gray-200 rounded-md px-2 py-1.5 bg-gray-50 text-gray-700" />
          </div>
        </div>
      )}
    </div>
  )
}
