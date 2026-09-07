/**
 * CompareProgress — Progression PUIS résultat du tableau comparatif.
 * ==================================================================
 * Se connecte au flux SSE et affiche l'avancement par groupe. À la fin, le tableau est
 * affiché à l'écran et le **format de sortie se choisit ici** (Excel · PDF · Word ·
 * Markdown) : les valeurs sont déjà extraites, changer de format ne relance pas l'IA.
 * Plus de téléchargement automatique — c'est l'utilisateur qui décide quoi emporter.
 */
import { useEffect, useRef, useState } from 'react'
import { CheckCircle, Circle, Loader, XCircle, Download, Copy, FileSpreadsheet, FileText, FileType2, Hash } from 'lucide-react'
import { clsx } from 'clsx'
import { compareApi, type CompareFormat, type CompareResultat } from '../../api'
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
          setEtats(prev => prev.map(g =>
            g.nom === event.groupe ? { ...g, statut: 'done' } : g
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
