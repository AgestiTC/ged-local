/**
 * PromptsSysteme — Paramètres › Prompts système (plan prompts, étapes A4-A5, 18/11/2026).
 * ======================================================================================
 * Voir et modifier les prompts que Matothèque envoie aux modèles (registre `services/prompts.py`),
 * sans redéploiement. Chaque enregistrement crée une NOUVELLE version (jamais d'écrasement) ;
 * « Revenir à l'origine » en crée une aussi (texte du code). Le serveur vérifie le contrat de la
 * clé (variables, accolades, longueur) et sert la version active aux deux processus sous 2 s.
 * « Essayer » et « Faire relire par l'IA » n'enregistrent rien et n'utilisent que l'IA locale.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, FlaskConical, History, RotateCcw, Save, Sparkles } from 'lucide-react'
import {
  extractApiError, systemApi,
  type PromptEssai, type PromptRelu, type PromptSysteme, type PromptSystemeDetail,
} from '../../api'
import { confirmerTexte } from '../common/Confirmation'
import { useToast } from '../common/Toast'
import {
  diffLignes, ecartVariables, libelleVersion, regrouperParUsage, resumeDiff,
} from '../../utils/promptsSysteme'

const AVERTISSEMENT = 'La modification s\'applique à TOUTES les analyses suivantes qui utilisent ce prompt, '
  + 'pour tout le monde, dans les 2 secondes.'

const dateFr = (iso: string | null) => (iso ? new Date(iso).toLocaleString('fr-FR') : '')

export function PromptsSysteme() {
  const toast = useToast()
  const [liste, setListe] = useState<PromptSysteme[] | null>(null)
  const [erreurListe, setErreurListe] = useState<string | null>(null)
  const [cle, setCle] = useState<string | null>(null)

  const charger = useCallback(async () => {
    try { setListe(await systemApi.promptsSysteme()); setErreurListe(null) }
    catch (e) { setErreurListe(extractApiError(e, 'Liste des prompts indisponible')) }
  }, [])
  useEffect(() => { void charger() }, [charger])

  const groupes = useMemo(() => regrouperParUsage(liste ?? []), [liste])

  if (erreurListe) return <p className="px-4 py-3 text-sm text-red-600">{erreurListe}</p>
  if (!liste) return <p className="px-4 py-3 text-sm text-gray-400">Chargement des prompts…</p>

  return (
    <div className="px-4 py-3 space-y-3">
      <p className="text-xs text-gray-500">
        Les prompts que Matothèque envoie aux modèles d'IA. Le texte d'origine reste dans le code ; chaque
        modification enregistrée ici devient une nouvelle version, et l'origine reste toujours restaurable.
      </p>
      <div className="grid gap-4 lg:grid-cols-[minmax(16rem,22rem)_1fr]">
        <nav className="space-y-3 max-h-[70vh] overflow-y-auto pr-1" aria-label="Prompts système">
          {groupes.map(g => (
            <div key={g.usage}>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">{g.libelle}</p>
              <ul className="space-y-0.5">
                {g.prompts.map(p => (
                  <li key={p.cle}>
                    <button type="button" onClick={() => setCle(p.cle)} title={p.description}
                      className={`w-full text-left px-2 py-1.5 rounded-md text-sm flex items-center gap-2 ${
                        cle === p.cle ? 'bg-amber-50 text-amber-800' : 'hover:bg-gray-50 text-gray-700'}`}>
                      <span className="font-mono text-xs truncate flex-1">{p.cle}</span>
                      {p.ignoree && <AlertTriangle size={12} className="text-red-500 shrink-0" aria-label="version ignorée" />}
                      {p.modifie && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 shrink-0">modifié</span>}
                      <span className="text-[10px] text-gray-400 shrink-0">{libelleVersion(p.version_active, !p.modifie)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="min-w-0">
          {cle
            ? <DetailPrompt key={cle} cle={cle} onChange={charger} toast={toast} />
            : <p className="text-sm text-gray-400 py-6">Choisissez un prompt dans la liste.</p>}
        </div>
      </div>
    </div>
  )
}

type Toast = ReturnType<typeof useToast>

/** Choix d'un texte à comparer : « origine », « edition » (texte en cours) ou un numéro de version. */
type Source = 'origine' | 'edition' | number

function DetailPrompt({ cle, onChange, toast }: { cle: string; onChange: () => void; toast: Toast }) {
  const [d, setD] = useState<PromptSystemeDetail | null>(null)
  const [texte, setTexte] = useState('')
  const [commentaire, setCommentaire] = useState('')
  const [occupe, setOccupe] = useState<'enregistrer' | 'origine' | 'essayer' | 'relire' | null>(null)
  const [diffA, setDiffA] = useState<Source>('origine')
  const [diffB, setDiffB] = useState<Source>('edition')
  const [valeurs, setValeurs] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const [essai, setEssai] = useState<PromptEssai | null>(null)
  const [relu, setRelu] = useState<PromptRelu | null>(null)

  const recharger = useCallback(async () => {
    const det = await systemApi.promptSysteme(cle)
    setD(det)
    setTexte(det.texte_actif)
    return det
  }, [cle])

  useEffect(() => {
    recharger().catch(e => toast.error(extractApiError(e, 'Prompt indisponible')))
  }, [recharger, toast])

  const texteDe = useCallback((s: Source): string => {
    if (!d) return ''
    if (s === 'origine') return d.origine
    if (s === 'edition') return texte
    const v = d.versions.find(x => x.version === s)
    return v ? (v.texte ?? d.origine) : ''
  }, [d, texte])

  const diff = useMemo(() => diffLignes(texteDe(diffA), texteDe(diffB)), [texteDe, diffA, diffB])
  const resume = resumeDiff(diff)

  if (!d) return <p className="text-sm text-gray-400 py-6">Chargement…</p>

  const actifOrigine = !d.active || d.active.origine
  const modifieEnCours = texte !== d.texte_actif
  const ecart = ecartVariables(texte, d.variables)
  const tropCourt = texte.trim().length < d.longueur_min
  const tropLong = texte.length > d.longueur_max

  const nouvelleVersion = async (contenu: string | null, note: string, quoi: 'enregistrer' | 'origine') => {
    setOccupe(quoi)
    try {
      const v = await systemApi.promptSystemeEnregistrer(cle, contenu, note || undefined)
      toast.success(contenu === null ? `Origine rétablie (version ${v.version}).` : `Version ${v.version} enregistrée et active.`)
      setCommentaire('')
      setRelu(null)
      await recharger()
      onChange()
    } catch (e) { toast.error(extractApiError(e, 'Enregistrement refusé')) } finally { setOccupe(null) }
  }

  const enregistrer = async () => {
    if (!await confirmerTexte(`Enregistrer une nouvelle version de « ${cle} » ?\n${AVERTISSEMENT}\n`
      + 'L\'ancienne version reste dans l\'historique.', 'Enregistrer')) return
    await nouvelleVersion(texte, commentaire.trim(), 'enregistrer')
  }

  const revenirOrigine = async () => {
    if (!await confirmerTexte(`Revenir au texte d'origine de « ${cle} » ?\n${AVERTISSEMENT}\n`
      + 'Une nouvelle version « origine » est créée ; les versions modifiées restent dans l\'historique.',
    'Revenir à l\'origine')) return
    await nouvelleVersion(null, commentaire.trim() || 'Retour à l\'origine', 'origine')
  }

  const restaurer = async (version: number, contenu: string | null) => {
    if (!await confirmerTexte(`Restaurer la version ${version} de « ${cle} » ?\n${AVERTISSEMENT}\n`
      + 'Elle devient une nouvelle version active ; rien n\'est effacé.', 'Restaurer')) return
    await nouvelleVersion(contenu, `Restauration de la version ${version}`, contenu === null ? 'origine' : 'enregistrer')
  }

  const essayer = async () => {
    setOccupe('essayer')
    setEssai(null)
    try { setEssai(await systemApi.promptSystemeEssayer(cle, { texte, variables: valeurs, message: message.trim() || null })) }
    catch (e) { toast.error(extractApiError(e, 'Essai impossible')) } finally { setOccupe(null) }
  }

  const relire = async () => {
    setOccupe('relire')
    setRelu(null)
    try { setRelu(await systemApi.promptSystemeRelire(cle, texte)) }
    catch (e) { toast.error(extractApiError(e, 'Relecture impossible')) } finally { setOccupe(null) }
  }

  const bouton = 'flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-lg disabled:opacity-40 transition-colors'
  const optionsSource = (
    <>
      <option value="origine">Origine (code)</option>
      <option value="edition">Texte en cours d'édition</option>
      {d.versions.map(v => <option key={v.version} value={v.version}>Version {v.version}{v.origine ? ' (origine)' : ''}</option>)}
    </>
  )
  const lireSource = (val: string): Source => (val === 'origine' || val === 'edition' ? val : Number(val))

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="font-mono text-sm font-semibold text-gray-800">{d.cle}</h3>
          <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">usage : {d.usage}</span>
          <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">sortie : {d.sortie}</span>
          <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
            active : {libelleVersion(d.active?.version ?? 0, actifOrigine)}
          </span>
          {!actifOrigine && <span className="text-[11px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">modifié</span>}
        </div>
        <p className="text-xs text-gray-500 mt-1">{d.description}</p>
        <p className="text-xs text-gray-500 mt-1">
          {d.variables.length
            ? <>Variables remplies par le code (à garder toutes) : {d.variables.map(v => <code key={v} className="mx-0.5 px-1 bg-gray-100 rounded">{`{${v}}`}</code>)} — une accolade littérale s'écrit doublée : <code>{'{{'}</code> <code>{'}}'}</code>.</>
            : 'Texte littéral : aucune variable, les accolades sont envoyées telles quelles.'}
        </p>
        {(d.garde_fous?.length ?? 0) > 0 && (
          <p className="text-xs text-gray-500 mt-1">
            Consignes à garder (une version qui en retire une est refusée) : {d.garde_fous!.map(g => <span key={g.nom} className="mx-0.5 px-1 bg-amber-50 text-amber-800 rounded">{g.libelle}</span>)}
          </p>
        )}
        {d.servie.ignoree && (
          <p className="mt-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
            La version {d.servie.ignoree.version} ne respecte plus le contrat du code : elle est ignorée et
            l'origine est servie. {d.servie.ignoree.raison}
          </p>
        )}
      </div>

      <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2 flex gap-1.5">
        <AlertTriangle size={14} className="shrink-0 mt-0.5" /> {AVERTISSEMENT}
      </p>

      <div className="space-y-2">
        <textarea value={texte} onChange={e => setTexte(e.target.value)} spellCheck={false}
          className="w-full min-h-[16rem] font-mono text-xs border border-gray-200 rounded-lg p-2 focus:outline-none focus:ring-1 focus:ring-amber-300"
          aria-label="Texte du prompt" />
        <div className="text-xs space-y-0.5">
          <p className="text-gray-400">{texte.length.toLocaleString('fr-FR')} caractères (entre {d.longueur_min} et {d.longueur_max.toLocaleString('fr-FR')}).</p>
          {ecart.manquantes.length > 0 && <p className="text-red-600">Variable(s) manquante(s) : {ecart.manquantes.map(v => `{${v}}`).join(', ')}</p>}
          {ecart.inconnues.length > 0 && <p className="text-red-600">Variable(s) inconnue(s) : {ecart.inconnues.map(v => `{${v}}`).join(', ')}</p>}
          {tropCourt && <p className="text-red-600">Texte trop court.</p>}
          {tropLong && <p className="text-red-600">Texte trop long.</p>}
        </div>
        <input value={commentaire} onChange={e => setCommentaire(e.target.value)} maxLength={300}
          placeholder="Commentaire de la version (facultatif) : ce qui change et pourquoi"
          className="w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5" />
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={enregistrer}
            disabled={occupe !== null || !modifieEnCours || tropCourt || tropLong
              || ecart.manquantes.length > 0 || ecart.inconnues.length > 0}
            className={`${bouton} border-amber-300 text-amber-700 hover:bg-amber-50`}><Save size={14} /> Enregistrer</button>
          <button type="button" onClick={revenirOrigine} disabled={occupe !== null || actifOrigine}
            className={`${bouton} border-gray-200 text-gray-700 hover:bg-gray-50`}><RotateCcw size={14} /> Revenir à l'origine</button>
          <button type="button" onClick={() => setTexte(d.texte_actif)} disabled={occupe !== null || !modifieEnCours}
            className={`${bouton} border-gray-200 text-gray-500 hover:bg-gray-50`}>Annuler l'édition</button>
          <button type="button" onClick={relire} disabled={occupe !== null}
            className={`${bouton} border-violet-200 text-violet-700 hover:bg-violet-50`}><Sparkles size={14} /> {occupe === 'relire' ? 'Relecture…' : 'Faire relire par l\'IA'}</button>
        </div>
      </div>

      {relu && (
        <div className="border border-violet-200 rounded-lg p-3 space-y-2 bg-violet-50/40">
          <p className="text-sm font-medium text-violet-800">Proposition de l'IA ({relu.model})</p>
          {relu.tronque && <p className="text-xs text-amber-700">Texte trop long : seul le début a été relu.</p>}
          {relu.remarques.length > 0 && (
            <ul className="text-xs text-gray-600 list-disc pl-4">{relu.remarques.map((r, i) => <li key={i}>{r}</li>)}</ul>
          )}
          {!relu.contrat_ok && (
            <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
              Cette proposition casse le contrat du prompt : elle ne peut pas être enregistrée telle quelle.
              <ul className="list-disc pl-4 mt-1">{relu.erreurs.map((e, i) => <li key={i}>{e}</li>)}</ul>
            </div>
          )}
          <pre className="text-xs font-mono whitespace-pre-wrap bg-white border border-gray-200 rounded p-2 max-h-72 overflow-auto">{relu.prompt}</pre>
          <button type="button" onClick={() => setTexte(relu.prompt)}
            className={`${bouton} border-violet-200 text-violet-700 hover:bg-violet-50`}>
            {relu.contrat_ok ? 'Reprendre dans l\'éditeur' : 'Reprendre dans l\'éditeur pour la corriger'}
          </button>
        </div>
      )}

      <details className="border border-gray-200 rounded-lg">
        <summary className="px-3 py-2 text-sm text-gray-700 cursor-pointer flex items-center gap-1.5">
          <FlaskConical size={14} className="text-teal-600" /> Essayer (rien n'est enregistré)
        </summary>
        <div className="px-3 pb-3 space-y-2">
          <p className="text-xs text-gray-500">
            Envoie le texte de l'éditeur au modèle local de l'usage « {d.usage} ». Les variables sont vides par défaut.
          </p>
          {d.variables.map(v => (
            <label key={v} className="block text-xs text-gray-600">
              <code>{`{${v}}`}</code>
              <textarea value={valeurs[v] ?? ''} rows={2} onChange={e => setValeurs(s => ({ ...s, [v]: e.target.value }))}
                className="mt-0.5 w-full font-mono text-xs border border-gray-200 rounded p-1.5" />
            </label>
          ))}
          <label className="block text-xs text-gray-600">
            Message de test (facultatif : le prompt part alors en consigne système, ce message en question)
            <textarea value={message} rows={2} onChange={e => setMessage(e.target.value)}
              className="mt-0.5 w-full text-xs border border-gray-200 rounded p-1.5" />
          </label>
          <button type="button" onClick={essayer} disabled={occupe !== null}
            className={`${bouton} border-teal-200 text-teal-700 hover:bg-teal-50`}>
            <FlaskConical size={14} /> {occupe === 'essayer' ? 'Envoi…' : 'Essayer'}
          </button>
          {essai && (
            <div className="space-y-1">
              <p className="text-xs text-gray-500">{essai.model} · {(essai.duree_ms / 1000).toLocaleString('fr-FR')} s</p>
              <pre className="text-xs font-mono whitespace-pre-wrap bg-gray-50 border border-gray-200 rounded p-2 max-h-72 overflow-auto">{essai.reponse}</pre>
            </div>
          )}
        </div>
      </details>

      <details className="border border-gray-200 rounded-lg" open>
        <summary className="px-3 py-2 text-sm text-gray-700 cursor-pointer">
          Différence ({resume.retraits} ligne(s) retirée(s), {resume.ajouts} ajoutée(s))
        </summary>
        <div className="px-3 pb-3 space-y-2">
          <div className="flex items-center gap-2 text-xs flex-wrap">
            <select value={String(diffA)} onChange={e => setDiffA(lireSource(e.target.value))}
              className="border border-gray-200 rounded px-1.5 py-1" aria-label="Texte de départ">{optionsSource}</select>
            <span className="text-gray-400">→</span>
            <select value={String(diffB)} onChange={e => setDiffB(lireSource(e.target.value))}
              className="border border-gray-200 rounded px-1.5 py-1" aria-label="Texte d'arrivée">{optionsSource}</select>
          </div>
          <pre className="text-xs font-mono bg-gray-50 border border-gray-200 rounded max-h-80 overflow-auto">
            {diff.map((l, i) => (
              <div key={i} className={l.type === 'ajout' ? 'bg-green-50 text-green-800' : l.type === 'retrait' ? 'bg-red-50 text-red-700 line-through' : 'text-gray-600'}>
                {l.type === 'ajout' ? '+ ' : l.type === 'retrait' ? '− ' : '  '}{l.texte || ' '}
              </div>
            ))}
          </pre>
        </div>
      </details>

      <details className="border border-gray-200 rounded-lg">
        <summary className="px-3 py-2 text-sm text-gray-700 cursor-pointer flex items-center gap-1.5">
          <History size={14} /> Historique ({d.versions.length} version(s))
        </summary>
        <div className="px-3 pb-3">
          {d.versions.length === 0
            ? <p className="text-xs text-gray-400">Jamais modifié : le texte servi est celui du code.</p>
            : (
              <ul className="divide-y divide-gray-100">
                {d.versions.map((v, i) => (
                  <li key={v.version} className="py-1.5 flex items-center gap-2 text-xs">
                    <span className="font-medium text-gray-700 w-24 shrink-0">
                      {`Version ${v.version}`}{v.origine ? ' · origine' : ''}{i === 0 ? ' · active' : ''}
                    </span>
                    <span className="text-gray-500 shrink-0">{dateFr(v.created_at)}</span>
                    {v.auteur && <span className="text-gray-500 shrink-0">par {v.auteur}</span>}
                    <span className="text-gray-600 truncate flex-1">{v.commentaire ?? ''}</span>
                    <button type="button" onClick={() => { setDiffA(v.version); setDiffB('edition') }}
                      className="text-blue-600 hover:underline shrink-0">Comparer</button>
                    {i > 0 && (
                      <button type="button" onClick={() => restaurer(v.version, v.texte)} disabled={occupe !== null}
                        className="text-amber-700 hover:underline shrink-0 disabled:opacity-40">Restaurer</button>
                    )}
                  </li>
                ))}
              </ul>
            )}
        </div>
      </details>
    </div>
  )
}
