/**
 * CompareProgress — Progression PUIS résultat du tableau comparatif.
 * ==================================================================
 * Se connecte au flux SSE et affiche l'avancement par groupe. À la fin, le tableau est
 * affiché à l'écran et le **format de sortie se choisit ici** (Excel · PDF · Word ·
 * Markdown) : les valeurs sont déjà extraites, changer de format ne relance pas l'IA.
 * Plus de téléchargement automatique — c'est l'utilisateur qui décide quoi emporter.
 */
import { useEffect, useRef, useState } from 'react'
import { CheckCircle, Circle, Loader, XCircle, Download, Copy, FileSpreadsheet, FileText, FileType2, Hash, Wrench } from 'lucide-react'
import { clsx } from 'clsx'
import { compareApi, suivreJob, type CompareFormat, type CompareResultat } from '../../api'
import type { CompareEvent } from '../../types'
import { copierTexte } from '../../utils/clipboard'
import { useToast } from '../common/Toast'

interface GroupeEtat {
  nom: string
  statut: 'pending' | 'running' | 'done' | 'error'
}

interface Props {
  jobId: string
  groupeNoms: string[]
  onComplete: () => void
  onError: (msg: string) => void
}

const EXPORTS: { format: CompareFormat; label: string; Icon: typeof FileText }[] = [
  { format: 'xlsx', label: 'Excel', Icon: FileSpreadsheet },
  { format: 'pdf', label: 'PDF', Icon: FileText },
  { format: 'docx', label: 'Word', Icon: FileType2 },
  { format: 'md', label: 'Markdown', Icon: Hash },
]

export default function CompareProgress({ jobId, groupeNoms, onComplete, onError }: Props) {
  const [etats, setEtats] = useState<GroupeEtat[]>(
    groupeNoms.map(nom => ({ nom, statut: 'pending' }))
  )
  const [done, setDone] = useState(false)
  const [etape, setEtape] = useState<string | null>(null)
  const [criteres, setCriteres] = useState<string[]>([])
  const [resultat, setResultat] = useState<CompareResultat | null>(null)
  const esRef = useRef<EventSource | null>(null)
  const toast = useToast()

  useEffect(() => {
    const url = compareApi.getStreamUrl(jobId)
    const es = new EventSource(url)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as CompareEvent

        if (event.statut === 'criteres' || event.statut === 'synthese') {
          if (event.colonnes) { setCriteres(event.colonnes); setEtape(null) }
          else if (event.message) setEtape(event.message)
        } else if (event.statut === 'running' && event.groupe) {
          setEtats(prev => prev.map(g =>
            g.nom === event.groupe ? { ...g, statut: 'running' } : g
          ))
        } else if (event.statut === 'done' && event.groupe) {
          // Un groupe que l'IA n'a pas su extraire n'est pas « terminé » : il s'affiche en erreur.
          setEtats(prev => prev.map(g =>
            g.nom === event.groupe ? { ...g, statut: event.echec_ia ? 'error' : 'done' } : g
          ))
        } else if (event.statut === 'complete') {
          es.close()
          setDone(true)
          setEtape(null)
          if (event.colonnes) setCriteres(event.colonnes)
          // Récupérer le tableau pour l'afficher — l'export vient ensuite, à la demande.
          compareApi.getResultat(jobId)
            .then(setResultat)
            .catch(() => toast.error('Tableau généré mais illisible — réessayez le téléchargement'))
          onComplete()
        } else if (event.statut === 'failed') {
          es.close()
          setEtats(prev => prev.map(g =>
            g.statut === 'running' ? { ...g, statut: 'error' } : g
          ))
          onError(event.erreur || 'Erreur lors de la comparaison')
        }
      } catch { /* ignorer */ }
    }

    es.onerror = () => {
      es.close()
      onError('Connexion SSE interrompue')
    }

    return () => es.close()
  }, [jobId])

  // Réparation SANS tout relancer : notes perdues, critères en échec, fiches manquantes (11/10/2026).
  const [reparation, setReparation] = useState(false)
  // Ce qu'il reste à réparer, compté pour le bandeau (12/10/2026 : bouton jugé trop discret).
  const manques = (resultat?.groupes ?? []).reduce((acc, g) => {
    const evs = Object.values(g.evaluations ?? {})
    acc.echecs += evs.filter(ev => ev.avis.startsWith('⚠')).length
    acc.notes += evs.filter(ev => ev.note === null && !ev.avis.startsWith('⚠')).length
    acc.fiches += ('fiche' in g && !g.fiche) ? 1 : 0
    acc.candidats += g.echec_ia && !evs.length ? 1 : 0
    return acc
  }, { notes: 0, echecs: 0, fiches: 0, candidats: 0 })
  const aReparer = manques.notes + manques.echecs + manques.fiches + manques.candidats > 0

  const reparer = async () => {
    setReparation(true)
    try {
      const { job_id } = await compareApi.reparer(jobId)
      const job = await suivreJob(job_id)
      if (job.statut !== 'completed') { toast.error(`Réparation impossible : ${job.erreur ?? 'Ollama ?'}`); return }
      const b = (job.resultat ?? {}) as { notes_recuperees?: number; criteres_reevalues?: number; fiches_redigees?: number }
      setResultat(await compareApi.getResultat(jobId))
      toast.success(`Réparé : ${b.notes_recuperees ?? 0} note(s) récupérée(s), ${b.criteres_reevalues ?? 0} critère(s) réévalué(s), `
        + `${b.fiches_redigees ?? 0} fiche(s) rédigée(s). Les exports sont à jour.`)
    } catch {
      toast.error('Réparation impossible (serveur ou Ollama ?)')
    } finally {
      setReparation(false)
    }
  }

  const copier = async () => {
    if (!resultat) return
    const ok = await copierTexte(resultat.markdown)
    if (ok) toast.success('Tableau copié (Markdown)')
    else toast.error('Copie impossible')
  }

  const nbDone = etats.filter(g => g.statut === 'done').length
  const total = etats.length
  const pct = total > 0 ? Math.round((nbDone / total) * 100) : 0

  return (
    <div className="space-y-4">
      {/* Barre de progression globale */}
      <div>
        <div className="flex justify-between items-center mb-1.5">
          <span className="text-xs font-medium text-gray-600">
            {done ? 'Terminé !' : etape ?? `Analyse en cours… ${nbDone}/${total}`}
          </span>
          <span className="text-xs text-gray-400">{pct}%</span>
        </div>
        <div className="w-full bg-gray-100 rounded-full h-2">
          <div
            className={clsx(
              'h-2 rounded-full transition-all duration-500',
              done ? 'bg-green-500' : 'bg-blue-500'
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Critères retenus (utile quand c'est l'IA qui les a déduits) */}
      {criteres.length > 0 && !resultat && (
        <div className="flex flex-wrap gap-1">
          {criteres.map(c => (
            <span key={c} className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-xs">{c}</span>
          ))}
        </div>
      )}

      {/* État par groupe */}
      <div className="space-y-1.5">
        {etats.map(groupe => (
          <div key={groupe.nom} className="flex items-center gap-2.5 text-xs">
            {groupe.statut === 'done' && <CheckCircle size={14} className="text-green-500 shrink-0" />}
            {groupe.statut === 'running' && <Loader size={14} className="text-blue-500 animate-spin shrink-0" />}
            {groupe.statut === 'pending' && <Circle size={14} className="text-gray-300 shrink-0" />}
            {groupe.statut === 'error' && <XCircle size={14} className="text-red-400 shrink-0" />}
            <span className={clsx(
              'truncate',
              groupe.statut === 'done' && 'text-gray-700 font-medium',
              groupe.statut === 'running' && 'text-blue-600 font-medium',
              groupe.statut === 'pending' && 'text-gray-400',
              groupe.statut === 'error' && 'text-red-400',
            )}>
              {groupe.nom}
            </span>
            {groupe.statut === 'running' && (
              <span className="text-blue-400 ml-auto shrink-0">analyse…</span>
            )}
            {groupe.statut === 'done' && (
              <span className="text-green-500 ml-auto shrink-0">✓</span>
            )}
          </div>
        ))}
      </div>

      {/* ── Résultat : le tableau, puis le choix du format ── */}
      {done && (
        <div className="space-y-3 border-t border-gray-100 pt-3">
          {/* Bandeau orange EN TÊTE du résultat : ce qui manque, et le bouton pour le réparer. */}
          {aReparer && (
            <div className="rounded-lg border-2 border-orange-400 bg-orange-50 p-3 space-y-2">
              <p className="text-xs font-semibold text-orange-900">⚠️ Résultat incomplet — à réparer</p>
              <p className="text-xs text-orange-900/90">
                {[manques.notes && `${manques.notes} note(s) vide(s)`,
                  manques.echecs && `${manques.echecs} critère(s) en échec`,
                  manques.fiches && `${manques.fiches} fiche(s) non produite(s)`,
                  manques.candidats && `${manques.candidats} candidat(s) en échec`]
                  .filter(Boolean).join(' · ')}
              </p>
              <button type="button" onClick={reparer} disabled={reparation}
                title="Récupère les notes, réévalue les critères en échec et rédige les fiches manquantes, sans tout relancer"
                className="flex items-center justify-center gap-2 w-full py-2.5 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold shadow-sm disabled:opacity-60 transition-colors">
                {reparation ? <Loader size={15} className="animate-spin" /> : <Wrench size={15} />}
                {reparation ? 'Réparation en cours… (quelques minutes)' : '🛠 Réparer sans tout relancer'}
              </button>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-gray-500 mr-1">Télécharger en</span>
            {EXPORTS.map(({ format, label, Icon }) => (
              <a
                key={format}
                href={compareApi.getDownloadUrl(jobId, format)}
                download={`comparatif.${format}`}
                className="flex items-center gap-1 px-2 py-1 rounded-md border border-gray-200 text-xs text-gray-600 hover:border-blue-300 hover:text-blue-700 transition-colors"
              >
                <Icon size={12} /> {label}
              </a>
            ))}
            <button
              type="button"
              onClick={copier}
              disabled={!resultat}
              className="flex items-center gap-1 px-2 py-1 rounded-md border border-gray-200 text-xs text-gray-600 hover:border-blue-300 hover:text-blue-700 disabled:opacity-50 transition-colors"
            >
              <Copy size={12} /> Copier
            </button>
          </div>

          {!resultat ? (
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <Loader size={13} className="animate-spin" /> Chargement du tableau…
            </div>
          ) : (
            <>
              {/* Tableau transposé : 1 ligne = 1 critère, 1 colonne = 1 entité comparée */}
              <div className="overflow-x-auto border border-gray-200 rounded-lg">
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="bg-gray-50">
                      <th className="text-left font-semibold text-gray-600 px-2.5 py-2 border-b border-gray-200">
                        Critère
                      </th>
                      {resultat.groupes.map(g => (
                        <th key={g.nom} className="text-left font-semibold text-gray-700 px-2.5 py-2 border-b border-l border-gray-200 min-w-[9rem]">
                          {g.nom}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {resultat.colonnes.map((col, i) => (
                      <tr key={col} className={i % 2 ? 'bg-gray-50/60' : undefined}>
                        <td className="align-top font-medium text-gray-600 px-2.5 py-1.5 border-b border-gray-100">
                          {col}
                        </td>
                        {resultat.groupes.map(g => (
                          <td key={g.nom} className="align-top text-gray-700 px-2.5 py-1.5 border-b border-l border-gray-100">
                            {g.valeurs?.[col] || '—'}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Offre lue en partie : à savoir avant de se fier à un « N/A » */}
              {resultat.groupes.some(g => (g.lu_pct ?? 100) < 100) && (
                <p className="text-xs text-amber-700">
                  Offres lues en partie (contexte de l'IA) :{' '}
                  {resultat.groupes.filter(g => (g.lu_pct ?? 100) < 100).map(g => `${g.nom} ${g.lu_pct} %`).join(' · ')}
                  {' '}— mettez les pièces utiles (mémoire technique, BPU) dans le groupe plutôt que tout le dossier.
                </p>
              )}

              {/* Classement : total pondéré et rang, calculés par Matothèque (pas par l'IA). */}
              {resultat.classement && (
                <div className="rounded-lg border border-amber-200 bg-amber-50/40 p-3 space-y-2">
                  <h3 className="text-xs font-semibold text-gray-800">🏆 Classement provisoire</h3>
                  <ol className="space-y-1.5">
                    {resultat.classement.lignes.map(l => (
                      <li key={l.nom} className="text-xs">
                        <div className="flex items-center gap-2">
                          <span className="w-7 shrink-0 font-semibold text-gray-700">
                            {({ 1: '🥇', 2: '🥈', 3: '🥉' } as Record<number, string>)[l.rang] ?? `${l.rang}.`}
                          </span>
                          <span className="flex-1 min-w-0 truncate text-gray-800">{l.nom}</span>
                          {l.incomplet && (
                            <span className="text-orange-700 shrink-0" title="Total partiel : note(s) manquante(s) ou critère en échec">
                              ⚠️ {l.notes_manquantes || ''}
                            </span>
                          )}
                          <span className="shrink-0 font-medium text-gray-700">{l.total} / {l.max}</span>
                          <span className="w-12 shrink-0 text-right text-gray-500">{l.pct} %</span>
                        </div>
                        <div className="ml-9 mt-0.5 h-1.5 rounded-full bg-gray-200 overflow-hidden">
                          <div className="h-full rounded-full bg-amber-500" style={{ width: `${Math.min(100, l.pct)}%` }} />
                        </div>
                      </li>
                    ))}
                  </ol>
                  <p className="text-[11px] text-gray-400">
                    Calculé à partir des notes proposées par l'IA — à valider par la commission. Dans l'Excel de la grille,
                    la feuille « Classement » se recalcule si une note est corrigée.
                  </p>
                </div>
              )}

              {/* Fiches points forts / faibles par candidat */}
              {resultat.groupes.some(g => 'fiche' in g) && (
                <div className="space-y-2">
                  <h3 className="text-xs font-semibold text-gray-700">Fiches candidats</h3>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {resultat.groupes.map(g => (
                      <div key={g.nom} className="rounded-lg border border-gray-200 p-3 text-xs space-y-1.5">
                        <p className="font-semibold text-gray-800">{g.nom}</p>
                        {!g.fiche ? (
                          <p className="text-gray-400 italic">Fiche non produite par l'IA.</p>
                        ) : (
                          <>
                            {g.fiche.resume && <p className="text-gray-600 leading-relaxed">{g.fiche.resume}</p>}
                            {([
                              ['Points forts', g.fiche.points_forts, 'text-green-700'],
                              ['Points faibles', g.fiche.points_faibles, 'text-red-700'],
                              ['Vigilance', g.fiche.vigilance, 'text-amber-700'],
                            ] as const).filter(([, puces]) => puces.length > 0).map(([titre, puces, couleur]) => (
                              <div key={titre}>
                                <p className={clsx('font-medium', couleur)}>{titre}</p>
                                <ul className="list-disc pl-4 text-gray-700 space-y-0.5">
                                  {puces.map((p, i) => <li key={i}>{p}</li>)}
                                </ul>
                              </div>
                            ))}
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                  <p className="text-[11px] text-gray-400">Proposition IA — à valider par la commission.</p>
                </div>
              )}

              {resultat.synthese && (
                <div className="rounded-lg bg-blue-50 border border-blue-100 p-3">
                  <h3 className="text-xs font-semibold text-blue-900 mb-1.5">Synthèse des écarts</h3>
                  <div className="text-xs text-blue-900/90 leading-relaxed whitespace-pre-wrap">
                    {resultat.synthese}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Repli si le navigateur bloque les liens de téléchargement */}
          <a
            href={compareApi.getDownloadUrl(jobId, 'xlsx')}
            download="comparatif.xlsx"
            className="flex items-center justify-center gap-2 w-full py-2 bg-green-600 hover:bg-green-700 text-white text-xs font-medium rounded-lg transition-colors"
          >
            <Download size={13} />
            Télécharger le tableau Excel
          </a>
        </div>
      )}
    </div>
  )
}
