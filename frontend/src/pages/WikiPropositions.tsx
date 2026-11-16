/**
 * WikiPropositions — les propositions de modification du wiki, pour les ADMINISTRATEURS (16/11/2026).
 * Tout utilisateur propose depuis le lecteur ; ici on relit (avant / après), on applique ou on refuse.
 * - page écrite dans BookStack → « Appliquer » écrit la page (étiquette : proposé par X, validé par Y) ;
 * - page d'un projet à jeton (sapyn…) → « Reportée » une fois corrigée à la main dans le projet ;
 * - page du cockpit → transmise au projet : c'est le cockpit qui applique (affichée pour mémoire).
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Check, Loader2, X, CornerDownRight } from 'lucide-react'
import { extractApiError, wikiApi, type WikiPropositionDetail } from '../api'
import { useToast } from '../components/common/Toast'
import { confirmerTexte, saisirTexte } from '../components/common/Confirmation'

type Ligne = { type: 'egal' | 'retire' | 'ajoute'; texte: string }

/** Différence ligne à ligne (plus longue sous-suite commune) — les pages du wiki sont courtes. */
export function diffLignes(avant: string, apres: string): Ligne[] {
  const a = avant.replace(/\r\n/g, '\n').split('\n')
  const b = apres.replace(/\r\n/g, '\n').split('\n')
  const n = a.length, m = b.length
  if (n * m > 4_000_000) return [...a.map(t => ({ type: 'retire' as const, texte: t })), ...b.map(t => ({ type: 'ajoute' as const, texte: t }))]
  const l: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    l[i][j] = a[i] === b[j] ? l[i + 1][j + 1] + 1 : Math.max(l[i + 1][j], l[i][j + 1])
  const out: Ligne[] = []
  let i = 0, j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ type: 'egal', texte: a[i] }); i++; j++ }
    else if (l[i + 1][j] >= l[i][j + 1]) out.push({ type: 'retire', texte: a[i++] })
    else out.push({ type: 'ajoute', texte: b[j++] })
  }
  while (i < n) out.push({ type: 'retire', texte: a[i++] })
  while (j < m) out.push({ type: 'ajoute', texte: b[j++] })
  return out
}

const LIBELLES: Record<string, string> = {
  proposee: 'À valider', a_reporter: 'À reporter dans le projet', transmise: 'Transmise au cockpit',
  appliquee: 'Appliquée', refusee: 'Refusée',
}

function Diff({ avant, apres }: { avant: string; apres: string }) {
  const lignes = useMemo(() => diffLignes(avant, apres), [avant, apres])
  return (
    <pre className="text-xs font-mono bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto max-h-96 whitespace-pre-wrap">
      {lignes.map((l, k) => (
        <div key={k} className={l.type === 'ajoute' ? 'bg-green-100 text-green-900' : l.type === 'retire' ? 'bg-red-100 text-red-900 line-through' : 'text-gray-500'}>
          {l.type === 'ajoute' ? '+ ' : l.type === 'retire' ? '- ' : '  '}{l.texte || ' '}
        </div>
      ))}
    </pre>
  )
}

export default function WikiPropositions() {
  const toast = useToast()
  const [props, setProps] = useState<WikiPropositionDetail[] | null>(null)
  const [toutes, setToutes] = useState(false)
  const [occupe, setOccupe] = useState<string | null>(null)

  const charger = () => wikiApi.propositions(toutes).then(setProps).catch(e => { toast.error(extractApiError(e)); setProps([]) })
  useEffect(() => { setProps(null); void charger() }, [toutes])   // eslint-disable-line react-hooks/exhaustive-deps

  const agir = async (p: WikiPropositionDetail, fn: () => Promise<unknown>, ok: string) => {
    setOccupe(p.id)
    try { await fn(); toast.success(ok); await charger() }
    catch (e) { toast.error(extractApiError(e)) } finally { setOccupe(null) }
  }

  const appliquer = (p: WikiPropositionDetail) => agir(p, async () => {
    try { await wikiApi.appliquerProposition(p.id) }
    catch (e) {
      const statut = (e as { response?: { status?: number } })?.response?.status
      if (statut !== 409) throw e
      if (!(await confirmerTexte(`${extractApiError(e)}\n\nAppliquer quand même ?`))) throw new Error('Non appliquée.')
      await wikiApi.appliquerProposition(p.id, true)
    }
  }, 'Appliquée dans BookStack.')

  const refuser = async (p: WikiPropositionDetail) => {
    const motif = await saisirTexte('Motif du refus (facultatif) :')
    if (motif === null) return
    await agir(p, () => wikiApi.refuserProposition(p.id, motif), 'Proposition refusée.')
  }

  const auteur = (a: WikiPropositionDetail['auteur']) =>
    a?.nom && a?.identifiant && a.nom !== a.identifiant ? `${a.nom} (${a.identifiant})` : (a?.nom || a?.identifiant || 'inconnu')

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b border-gray-200 bg-white flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Link to="/wiki/livres" className="text-gray-400 hover:text-gray-600"><ArrowLeft size={18} /></Link>
          <h1 className="text-base font-bold text-gray-800">Wiki — Propositions de modification</h1>
        </div>
        <label className="text-xs text-gray-600 flex items-center gap-1.5">
          <input type="checkbox" checked={toutes} onChange={e => setToutes(e.target.checked)} /> Afficher aussi l'historique
        </label>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-gray-50">
        {props === null ? (
          <div className="flex justify-center py-12"><Loader2 size={20} className="animate-spin text-gray-400" /></div>
        ) : props.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-12">Aucune proposition {toutes ? '' : 'en attente'}.</p>
        ) : props.map(p => (
          <div key={p.id} className="bg-white border border-gray-200 rounded-lg p-3 space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Link to={p.book_id ? `/wiki/livres/${p.book_id}` : '/wiki/livres'} className="font-semibold text-blue-700 hover:underline">{p.titre}</Link>
              <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{LIBELLES[p.statut] ?? p.statut}</span>
              {p.projet && <span className="text-xs text-gray-500">projet {p.projet}{p.cle ? ` · ${p.cle}.md` : ''}</span>}
              {p.converti && <span className="text-xs text-amber-700" title="Page écrite avec l'éditeur visuel : l'appliquer la fait passer en Markdown dans BookStack">page HTML convertie</span>}
              <span className="text-xs text-gray-400 ml-auto">{auteur(p.auteur)} · {p.created_at ? new Date(p.created_at).toLocaleString('fr-FR') : ''}</span>
            </div>
            {p.commentaire && <p className="text-xs text-gray-600"><CornerDownRight size={12} className="inline" /> {p.commentaire}</p>}
            <Diff avant={p.markdown_avant} apres={p.markdown_propose} />
            {p.decide_par && <p className="text-xs text-gray-500">Décidé par {p.decide_par}{p.motif ? ` — ${p.motif}` : ''}</p>}
            <div className="flex gap-2 justify-end">
              {p.statut === 'proposee' && (
                <button type="button" disabled={occupe === p.id} onClick={() => void appliquer(p)}
                  className="text-xs flex items-center gap-1 px-3 py-1.5 rounded-md bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">
                  <Check size={13} /> Appliquer dans BookStack</button>
              )}
              {p.statut === 'a_reporter' && (
                <button type="button" disabled={occupe === p.id}
                  onClick={() => void agir(p, () => wikiApi.propositionReportee(p.id, ''), 'Marquée reportée dans le projet.')}
                  className="text-xs flex items-center gap-1 px-3 py-1.5 rounded-md bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">
                  <Check size={13} /> Reportée dans le projet</button>
              )}
              {(p.statut === 'proposee' || p.statut === 'a_reporter') && (
                <button type="button" disabled={occupe === p.id} onClick={() => void refuser(p)}
                  className="text-xs flex items-center gap-1 px-3 py-1.5 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                  <X size={13} /> Refuser</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
