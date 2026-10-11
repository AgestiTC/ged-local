/**
 * ConsigneBaseModal — voir et modifier les consignes de base (documents de référence), 11/10/2026.
 * ==============================================================================================
 * Deux consignes : « Analyse » et « Version corrigée ». Lecture par défaut ; « Modifier » ouvre
 * l'édition, AVEC GARDE-FOUS :
 *   - vérification de la structure avant enregistrement (verifierConsigne) + refus serveur ;
 *   - confirmation, et chaque enregistrement est une NOUVELLE version (jamais d'écrasement) ;
 *   - historique : voir / restaurer une version (= une version de plus) ;
 *   - « Rétablir la consigne d'origine » toujours possible.
 * Les critères de la grille et les instructions complémentaires sont ajoutés par Matothèque en
 * dehors de cette partie : les modifier ici ne peut pas les faire disparaître.
 */
import { useCallback, useEffect, useState } from 'react'
import { History, Loader2, Pencil, RotateCcw, Save, X } from 'lucide-react'
import { clsx } from 'clsx'
import { consignesApi, type CleConsigne, type ConsigneVersionInfo } from '../../api'
import { CORPS_ANALYSE_DEFAUT, CORPS_CORRIGEE_DEFAUT, verifierConsigne } from '../../utils/promptAnalyseReference'
import { useToast } from '../common/Toast'

const ONGLETS: { cle: CleConsigne; libelle: string; defaut: string }[] = [
  { cle: 'reference_analyse', libelle: '✨ Analyse', defaut: CORPS_ANALYSE_DEFAUT },
  { cle: 'reference_corrigee', libelle: '✏️ Version corrigée', defaut: CORPS_CORRIGEE_DEFAUT },
]

const dateFr = (iso: string | null) => (iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '')

export default function ConsigneBaseModal({ onClose }: { onClose: () => void }) {
  const [onglet, setOnglet] = useState<CleConsigne>('reference_analyse')
  const [versions, setVersions] = useState<ConsigneVersionInfo[]>([])
  const [chargement, setChargement] = useState(true)
  const [edition, setEdition] = useState<string | null>(null)
  const [commentaire, setCommentaire] = useState('')
  const [vue, setVue] = useState<number | null>(null)
  const [envoi, setEnvoi] = useState(false)
  const toast = useToast()

  const defaut = ONGLETS.find(o => o.cle === onglet)!.defaut
  const active = versions[0] ?? null
  const texteActif = active?.texte ?? defaut

  const charger = useCallback(() => {
    setChargement(true)
    consignesApi.get(onglet)
      .then(r => setVersions(r.versions))
      .catch(() => toast.error('Consignes illisibles (serveur ?)'))
      .finally(() => setChargement(false))
  }, [onglet, toast])

  useEffect(() => { setEdition(null); setVue(null); charger() }, [charger])

  const enregistrer = async (texte: string | null, note: string) => {
    setEnvoi(true)
    try {
      const v = await consignesApi.enregistrer(onglet, texte, note)
      toast.success(`Version ${v.version} enregistrée${v.origine ? ' (consigne d\'origine)' : ''}`)
      setEdition(null)
      setCommentaire('')
      charger()
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Enregistrement impossible')
    } finally {
      setEnvoi(false)
    }
  }

  const sauvegarderEdition = () => {
    if (edition === null) return
    const problemes = verifierConsigne(edition)
    if (problemes.length) { toast.error(`Garde-fou : ${problemes.join(' ')}`); return }
    if (edition.trim() === texteActif.trim()) { toast.error('Aucune modification à enregistrer'); return }
    if (!window.confirm(`Enregistrer cette consigne comme version ${(active?.version ?? 0) + 1} ?\n`
      + 'La version actuelle reste dans l\'historique et peut être restaurée.')) return
    enregistrer(edition, commentaire)
  }

  const restaurer = (v: ConsigneVersionInfo) => {
    if (!window.confirm(`Restaurer la version ${v.version} ? Elle deviendra une nouvelle version active.`)) return
    enregistrer(v.texte, `Restauration de la version ${v.version}`)
  }

  const retablirOrigine = () => {
    if (!window.confirm('Rétablir la consigne d\'origine de Matothèque ? Vos versions restent dans l\'historique.')) return
    enregistrer(null, 'Retour à la consigne d\'origine')
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col text-sm" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
          <h2 className="font-semibold text-gray-800">📄 Consignes de base — documents de référence</h2>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-gray-400 hover:text-gray-700"><X size={16} /></button>
        </div>

        <div className="flex gap-1 px-5 pt-3">
          {ONGLETS.map(o => (
            <button key={o.cle} type="button" onClick={() => setOnglet(o.cle)}
              className={clsx('px-3 py-1.5 rounded-md text-xs font-medium',
                onglet === o.cle ? 'bg-violet-100 text-violet-800' : 'text-gray-500 hover:bg-gray-50')}>
              {o.libelle}
            </button>
          ))}
        </div>

        <div className="px-5 py-3 overflow-y-auto space-y-3">
          {chargement ? (
            <p className="flex items-center gap-1.5 text-gray-400 text-xs"><Loader2 size={12} className="animate-spin" /> Chargement…</p>
          ) : (
            <>
              <p className="text-xs text-gray-500">
                Version active : <strong>{!active || active.origine ? 'consigne d\'origine' : `version ${active.version}`}</strong>
                {active && ` — ${dateFr(active.created_at)}`}
                {active?.commentaire && ` · ${active.commentaire}`}
                <br />Les critères de la grille et vos instructions complémentaires sont ajoutés automatiquement à la suite.
              </p>

              {edition === null ? (
                <pre className="whitespace-pre-wrap font-mono text-xs text-gray-700 bg-gray-50 border border-gray-200 rounded-lg p-3 max-h-80 overflow-y-auto">
                  {texteActif}
                </pre>
              ) : (
                <div className="space-y-2">
                  <textarea value={edition} onChange={e => setEdition(e.target.value)} rows={16}
                    className="w-full font-mono text-xs border border-violet-300 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-violet-300" />
                  <input value={commentaire} onChange={e => setCommentaire(e.target.value)} maxLength={300}
                    placeholder="Ce qui change dans cette version (facultatif)"
                    className="w-full text-xs border border-gray-200 rounded-md px-2.5 py-1.5" />
                  {verifierConsigne(edition).map(p => <p key={p} className="text-xs text-amber-700">⚠️ {p}</p>)}
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                {edition === null ? (
                  <button type="button" onClick={() => setEdition(texteActif)}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-violet-600 text-white hover:bg-violet-700">
                    <Pencil size={12} /> Modifier
                  </button>
                ) : (
                  <>
                    <button type="button" onClick={sauvegarderEdition} disabled={envoi}
                      className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60">
                      {envoi ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Enregistrer une nouvelle version
                    </button>
                    <button type="button" onClick={() => setEdition(null)}
                      className="text-xs px-3 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">Annuler</button>
                  </>
                )}
                {active && !active.origine && edition === null && (
                  <button type="button" onClick={retablirOrigine} disabled={envoi}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">
                    <RotateCcw size={12} /> Rétablir la consigne d'origine
                  </button>
                )}
              </div>

              {versions.length > 0 && (
                <div className="space-y-1.5">
                  <p className="flex items-center gap-1.5 text-xs font-semibold text-gray-700"><History size={12} /> Historique</p>
                  <ul className="space-y-1">
                    {versions.map((v, i) => (
                      <li key={v.version} className="rounded-md border border-gray-200 text-xs">
                        <div className="flex items-center gap-2 px-2.5 py-1.5">
                          <span className="font-medium text-gray-800">v{v.version}</span>
                          <span className="text-gray-400">{dateFr(v.created_at)}</span>
                          <span className="flex-1 min-w-0 truncate text-gray-600">
                            {v.origine ? 'Consigne d\'origine' : (v.commentaire || 'Modification')}
                          </span>
                          {i === 0 && <span className="text-green-700">active</span>}
                          <button type="button" onClick={() => setVue(vue === v.version ? null : v.version)}
                            className="text-blue-600 hover:underline">{vue === v.version ? 'Masquer' : 'Voir'}</button>
                          {i > 0 && (
                            <button type="button" onClick={() => restaurer(v)} disabled={envoi}
                              className="text-violet-700 hover:underline">Restaurer</button>
                          )}
                        </div>
                        {vue === v.version && (
                          <pre className="whitespace-pre-wrap font-mono text-[11px] text-gray-600 bg-gray-50 border-t border-gray-100 p-2.5 max-h-60 overflow-y-auto">
                            {v.texte ?? defaut}
                          </pre>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
