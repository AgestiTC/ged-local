/**
 * RetourReponse — 👍 / 👎, « Corriger » et pertinence des sources (plan RAG, étape B3)
 * ===================================================================================
 * Sous une réponse de l'IA qui a une ligne au journal (`journalId`) : chat, mode Question de la GED,
 * détail d'une question dans « Mes questions ». Un clic, jamais obligatoire ; chaque clic s'enregistre
 * seul (re-cliquer le même bouton le retire). Après un 👎, la liste des sources s'ouvre : c'est là que
 * se dit quel document était hors sujet. Ces retours serviront au classement (B4) et aux fiches (B5).
 */
import { useEffect, useState } from 'react'
import { Check, ChevronDown, ChevronRight, Loader2, PencilLine, ThumbsDown, ThumbsUp, X } from 'lucide-react'
import { clsx } from 'clsx'
import {
  journalQuestionsApi,
  type AvisRag, type JugementSource, type RetourPatch, type RetourReponse as Retour,
} from '../../api'

export type SourceJugeable = { id: string | null; nom: string }

const VIDE: Retour = { avis: null, correction: null, sources: {} }

export default function RetourReponse({ journalId, sources = [], valeur = null, onChange, sourcesOuvertes = false }: {
  journalId: string
  sources?: SourceJugeable[]
  valeur?: Retour | null
  onChange?: (r: Retour | null) => void
  /** Liste des sources dépliée d'emblée (détail du journal). */
  sourcesOuvertes?: boolean
}) {
  const [retour, setRetour] = useState<Retour>(valeur ?? VIDE)
  const [enCours, setEnCours] = useState(false)
  const [erreur, setErreur] = useState(false)
  const [voirSources, setVoirSources] = useState(sourcesOuvertes)
  const [edition, setEdition] = useState<string | null>(null)   // texte de la correction en cours d'écriture

  // Une autre réponse (ou un retour rechargé) : on repart de la valeur fournie.
  useEffect(() => { setRetour(valeur ?? VIDE) }, [journalId, valeur])

  const jugeables = sources.filter((s): s is { id: string; nom: string } => !!s.id)

  const envoyer = async (patch: RetourPatch, local: Retour) => {
    const avant = retour
    setRetour(local); setEnCours(true); setErreur(false)   // affichage immédiat, le serveur confirme
    try {
      const garde = await journalQuestionsApi.juger(journalId, patch)
      setRetour(garde ?? VIDE)
      onChange?.(garde)
      return true
    } catch {
      setRetour(avant); setErreur(true)
      return false
    } finally { setEnCours(false) }
  }

  const donnerAvis = (a: AvisRag) => {
    const avis = retour.avis === a ? null : a
    if (avis === 'inutile' && jugeables.length > 0) setVoirSources(true)
    void envoyer({ avis }, { ...retour, avis })
  }
  const jugerSource = (id: string, j: JugementSource) => {
    const jugement = retour.sources[id] === j ? null : j
    const suivantes = { ...retour.sources }
    if (jugement) suivantes[id] = jugement; else delete suivantes[id]
    void envoyer({ sources: { [id]: jugement } }, { ...retour, sources: suivantes })
  }
  const enregistrerCorrection = async () => {
    const texte = (edition ?? '').trim() || null
    if (await envoyer({ correction: texte }, { ...retour, correction: texte })) setEdition(null)
  }

  const bouton = (actif: boolean, couleur: string) => clsx(
    'p-1 rounded-md transition-colors disabled:opacity-50',
    actif ? couleur : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100')

  return (
    <div className="mt-1 text-[11px] text-gray-500" data-testid="retour-reponse">
      <div className="flex flex-wrap items-center gap-1">
        <span className="mr-0.5">Cette réponse vous aide ?</span>
        <button type="button" onClick={() => donnerAvis('utile')} disabled={enCours}
          aria-pressed={retour.avis === 'utile'} aria-label="Réponse utile" title="Réponse utile"
          className={bouton(retour.avis === 'utile', 'text-emerald-700 bg-emerald-50')}>
          <ThumbsUp size={13} />
        </button>
        <button type="button" onClick={() => donnerAvis('inutile')} disabled={enCours}
          aria-pressed={retour.avis === 'inutile'} aria-label="Réponse pas utile" title="Réponse pas utile"
          className={bouton(retour.avis === 'inutile', 'text-red-600 bg-red-50')}>
          <ThumbsDown size={13} />
        </button>
        <button type="button" onClick={() => setEdition(edition === null ? (retour.correction ?? '') : null)}
          className={clsx('flex items-center gap-1 px-1.5 py-0.5 rounded-md hover:bg-gray-100',
            retour.correction ? 'text-violet-700' : 'text-gray-500')}
          title="Écrire la bonne réponse — elle servira de référence">
          <PencilLine size={12} /> {retour.correction ? 'Corrigée' : 'Corriger'}
        </button>
        {jugeables.length > 0 && (
          <button type="button" onClick={() => setVoirSources(v => !v)} aria-expanded={voirSources}
            className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-md hover:bg-gray-100">
            {voirSources ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            Sources ({Object.keys(retour.sources).length}/{jugeables.length} jugée{jugeables.length > 1 ? 's' : ''})
          </button>
        )}
        {enCours && <Loader2 size={12} className="animate-spin text-gray-400" />}
        {erreur && <span className="text-red-500">Retour non enregistré</span>}
      </div>

      {voirSources && jugeables.length > 0 && (
        <ul className="mt-1 space-y-0.5" aria-label="Pertinence des sources">
          {jugeables.map(s => {
            const j = retour.sources[s.id]
            return (
              <li key={s.id} className="flex items-center gap-1 pl-1">
                <span className="truncate max-w-[22rem] text-gray-600" title={s.nom}>{s.nom}</span>
                <button type="button" onClick={() => jugerSource(s.id, 'pertinent')} disabled={enCours}
                  aria-pressed={j === 'pertinent'} aria-label={`${s.nom} : pertinent`}
                  className={clsx('flex items-center gap-0.5 px-1.5 py-0.5 rounded-md border disabled:opacity-50',
                    j === 'pertinent' ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-transparent hover:bg-gray-100')}>
                  <Check size={11} /> pertinent
                </button>
                <button type="button" onClick={() => jugerSource(s.id, 'hors_sujet')} disabled={enCours}
                  aria-pressed={j === 'hors_sujet'} aria-label={`${s.nom} : hors sujet`}
                  className={clsx('flex items-center gap-0.5 px-1.5 py-0.5 rounded-md border disabled:opacity-50',
                    j === 'hors_sujet' ? 'border-red-300 bg-red-50 text-red-600' : 'border-transparent hover:bg-gray-100')}>
                  <X size={11} /> hors sujet
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {edition !== null && (
        <div className="mt-1 space-y-1">
          <textarea value={edition} onChange={e => setEdition(e.target.value)} rows={3} autoFocus
            aria-label="Réponse corrigée" placeholder="La bonne réponse, telle que vous l'auriez attendue…"
            className="w-full text-xs border border-gray-200 rounded-md px-2 py-1 focus:outline-none focus:ring-2 focus:ring-violet-300" />
          <div className="flex gap-1.5">
            <button type="button" onClick={enregistrerCorrection} disabled={enCours}
              className="px-2 py-0.5 rounded-md bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50">
              Enregistrer
            </button>
            <button type="button" onClick={() => setEdition(null)}
              className="px-2 py-0.5 rounded-md border border-gray-200 hover:bg-gray-50">
              Annuler
            </button>
            <span className="self-center text-gray-400">Laisser vide puis Enregistrer retire la correction.</span>
          </div>
        </div>
      )}
      {edition === null && retour.correction && (
        <p className="mt-1 pl-1 whitespace-pre-wrap text-gray-600 border-l-2 border-violet-200">
          <span className="text-violet-700">Votre correction : </span>{retour.correction}
        </p>
      )}
    </div>
  )
}
