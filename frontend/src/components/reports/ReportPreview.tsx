/**
 * ReportPreview — panneau de résultat de la page « Créer »
 * ========================================================
 * Quatre onglets :
 *   • Aperçu  → check-list de PRÉPARATION (figée au lancement) + bloc « réflexion/avancement »
 *              vivant. C'est le tableau de bord de la génération, pas le document.
 *   • Rendu   → le document RENDU (Markdown → HTML) en streaming + barre de téléchargement
 *              (PDF · DOCX · Markdown · Wiki).
 *   • Source  → Markdown brut.
 *   • Éditer  → édition inline avant export.
 * Rendu/Source/Éditer n'apparaissent qu'une fois une génération démarrée (avant : seul Aperçu).
 */
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { BookOpen, Copy, Download, FileText, Hash, RotateCcw, RefreshCw } from 'lucide-react'
import { clsx } from 'clsx'
import { useReportStore } from '../../stores/reportStore'
import { useDocumentStore } from '../../stores/documentStore'
import LoadingSpinner from '../common/LoadingSpinner'
import PublishBookStackModal from '../common/PublishBookStackModal'
import ReportHistory from './ReportHistory'
import { useToast } from '../common/Toast'

/** Déduit un titre par défaut depuis le 1er titre Markdown (ou une valeur générique). */
function titreParDefaut(markdown: string): string {
  const ligne = markdown.split('\n').find(l => l.trim().startsWith('#'))
  return ligne ? ligne.replace(/^#+\s*/, '').trim().slice(0, 120) : 'Nouveau tuto'
}

const MODE_LABEL: Record<string, string> = {
  rapport_libre: 'Rapport libre', remplir_template: 'Remplir un template',
  classement: 'Classement / tri', comparatif: 'Comparatif', wiki: 'Tuto wiki',
}

type Onglet = 'apercu' | 'rendu' | 'source' | 'edit' | 'historique'

export default function ReportPreview() {
  const {
    rapportEnCours, rapportFinal, isGenerating, error, startedAt, prepSnapshot,
    resetRapport, exportPdf, exportDocx, exportMarkdown, startGeneration, editRapport,
    outputMode, prompt,
  } = useReportStore()
  const { selectedIds } = useDocumentStore()
  const isWiki = outputMode === 'wiki'

  const [mode, setMode] = useState<Onglet>('apercu')
  const [exporting, setExporting] = useState<'pdf' | 'docx' | 'md' | null>(null)
  const [showPublish, setShowPublish] = useState(false)
  const toast = useToast()

  const contenu = rapportEnCours || rapportFinal
  const aResultat = !!contenu || isGenerating   // Rendu/Source/Éditer disponibles

  // Bascule AUTOMATIQUE sur « Rendu » au lancement d'une génération : l'utilisateur voit le
  // document se construire sans changer d'onglet. On ne le force qu'au front montant.
  const etaitGeneration = useRef(false)
  useEffect(() => {
    if (isGenerating && !etaitGeneration.current) setMode('rendu')
    etaitGeneration.current = isGenerating
  }, [isGenerating])

  // Si l'onglet actif devient indisponible (reset → plus de contenu), revenir sur Aperçu.
  useEffect(() => {
    if (!aResultat && mode !== 'apercu') setMode('apercu')
  }, [aResultat, mode])

  // Chrono d'avancement (tick chaque seconde pendant la génération).
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!isGenerating) return
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [isGenerating])

  const copier = async () => {
    await navigator.clipboard.writeText(contenu)
    toast.success('Copié dans le presse-papier')
  }

  const handleExport = async (type: 'pdf' | 'docx' | 'md') => {
    setExporting(type)
    try {
      const titre = titreParDefaut(contenu)
      if (type === 'pdf') await exportPdf()
      else if (type === 'docx') await exportDocx()
      else { exportMarkdown(titre); }
      toast.success(`Export ${type.toUpperCase()} téléchargé`)
    } catch {
      toast.error(`Erreur export ${type.toUpperCase()}`)
    } finally {
      setExporting(null)
    }
  }

  // ── Check-list de préparation : instantané FIGÉ pendant la génération, valeurs vives avant. ──
  const nbDocs = prepSnapshot?.nbDocs ?? selectedIds.size
  const modeAffiche = prepSnapshot?.mode ?? outputMode
  const promptDefini = prepSnapshot?.promptDefini ?? !!prompt.trim()

  // ── Bloc « réflexion / avancement ». ──
  const secondes = startedAt ? Math.floor((Date.now() - startedAt) / 1000) : 0
  void tick // force le recalcul de `secondes` à chaque seconde
  const chrono = secondes >= 60 ? `${Math.floor(secondes / 60)} min ${secondes % 60}s` : `${secondes}s`
  const avancement = (): { icone: string; texte: string; sousTexte?: string } => {
    if (error) return { icone: '⚠️', texte: 'Échec de la génération', sousTexte: error }
    if (isGenerating && !contenu) return { icone: '⏳', texte: 'Le modèle réfléchit…', sousTexte: `Rédaction imminente · ${chrono}` }
    if (isGenerating) return { icone: '✍️', texte: `Rédaction en cours — ${contenu.length.toLocaleString('fr')} caractères`, sousTexte: chrono }
    if (contenu) return { icone: '✅', texte: `Rapport prêt — ${contenu.length.toLocaleString('fr')} caractères`, sousTexte: 'Onglet « Rendu » pour le lire et le télécharger.' }
    return { icone: '🕓', texte: 'En attente', sousTexte: 'Cliquez sur « Générer » pour lancer.' }
  }
  const av = avancement()

  // Historique TOUJOURS accessible (comme Aperçu) ; Rendu/Source/Éditer seulement s'il y a un résultat.
  const ongletsDispo: Onglet[] = aResultat
    ? ['apercu', 'rendu', 'source', 'edit', 'historique']
    : ['apercu', 'historique']
  // À vide, l'onglet « Aperçu » n'est pas un aperçu (rien à prévisualiser) mais un récapitulatif
  // de préparation → on le nomme « Récapitulatif » tant qu'aucun contenu n'a été généré.
  const LABEL: Record<Onglet, string> = {
    apercu: aResultat ? 'Aperçu' : 'Récapitulatif', rendu: 'Rendu', source: 'Source', edit: 'Éditer', historique: 'Historique',
  }

  return (
    <div className="flex flex-col h-full">
      {/* Barre d'outils */}
      <div className="flex items-center justify-between mb-2 shrink-0">
        <div className="flex rounded-md border border-gray-200 overflow-hidden text-xs">
          {ongletsDispo.map(m => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={clsx('px-2.5 py-1', mode === m ? 'bg-gray-100 font-medium text-gray-800' : 'text-gray-500 hover:text-gray-700')}
            >
              {LABEL[m]}
            </button>
          ))}
        </div>

        {/* Actions d'export : uniquement dans l'onglet Rendu, quand il y a du contenu. */}
        {mode === 'rendu' && contenu && (
          <div className="flex items-center gap-1">
            <button onClick={copier} title="Copier" className="p-1.5 text-gray-400 hover:text-gray-700 rounded-md hover:bg-gray-100">
              <Copy size={13} />
            </button>
            <button onClick={() => handleExport('pdf')} disabled={!!exporting} title="Exporter en PDF"
              className="flex items-center gap-1 text-xs px-2 py-1.5 text-gray-600 hover:bg-gray-100 rounded-md disabled:opacity-40">
              {exporting === 'pdf' ? <LoadingSpinner size={12} /> : <Download size={12} />} PDF
            </button>
            <button onClick={() => handleExport('docx')} disabled={!!exporting} title="Exporter en DOCX (Word)"
              className="flex items-center gap-1 text-xs px-2 py-1.5 text-gray-600 hover:bg-gray-100 rounded-md disabled:opacity-40">
              {exporting === 'docx' ? <LoadingSpinner size={12} /> : <FileText size={12} />} DOCX
            </button>
            <button onClick={() => handleExport('md')} disabled={!!exporting} title="Télécharger le Markdown (.md)"
              className="flex items-center gap-1 text-xs px-2 py-1.5 text-gray-600 hover:bg-gray-100 rounded-md disabled:opacity-40">
              {exporting === 'md' ? <LoadingSpinner size={12} /> : <Hash size={12} />} MD
            </button>
            <button onClick={() => setShowPublish(true)} disabled={isGenerating || !contenu}
              title="Publier comme tuto sur le wiki BookStack"
              className="flex items-center gap-1 text-xs px-2 py-1.5 text-purple-600 hover:bg-purple-50 rounded-md disabled:opacity-40">
              <BookOpen size={12} /> Wiki
            </button>
            <button onClick={() => startGeneration([...selectedIds])} disabled={isGenerating || selectedIds.size === 0}
              title={selectedIds.size === 0 ? 'Sélectionnez des documents pour régénérer' : 'Régénérer avec la sélection et le prompt actuels'}
              className="flex items-center gap-1 text-xs px-2 py-1.5 text-gray-600 hover:bg-gray-100 rounded-md disabled:opacity-40">
              <RefreshCw size={12} className={isGenerating ? 'animate-spin' : ''} /> Régénérer
            </button>
            <button onClick={resetRapport} title="Effacer" className="p-1.5 text-gray-400 hover:text-gray-700 rounded-md hover:bg-gray-100">
              <RotateCcw size={13} />
            </button>
          </div>
        )}
      </div>

      {/* Corps */}
      <div className="flex-1 overflow-y-auto min-h-0 rounded-lg border border-gray-200 bg-white">

        {/* ── APERÇU : préparation figée + avancement ── */}
        {mode === 'apercu' && (
          <div className="h-full p-5 flex flex-col gap-4">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{isWiki ? 'Votre tuto' : 'Votre rapport'}</p>
            <ul className="space-y-2 text-sm text-gray-600">
              <li className="flex items-center gap-2">
                <span>{nbDocs > 0 ? '✅' : isWiki ? '➖' : '⬜'}</span>
                Documents : <strong>{nbDocs}</strong>{' '}
                {isWiki && nbDocs === 0 ? '(optionnel)' : `sélectionné${nbDocs > 1 ? 's' : ''}`}
              </li>
              <li className="flex items-center gap-2">
                <span>📄</span> Mode : <strong>{MODE_LABEL[modeAffiche] ?? modeAffiche}</strong>
              </li>
              <li className="flex items-center gap-2">
                <span>{promptDefini ? '✅' : '⬜'}</span>
                {isWiki ? 'Sujet du tuto' : 'Instruction'} : <strong>{promptDefini ? 'défini' : 'à renseigner'}</strong>
              </li>
            </ul>

            {/* Bloc réflexion/avancement — figé sous la check-list, vivant pendant la génération. */}
            <div className={clsx('rounded-lg border p-3 text-sm flex items-start gap-2',
              error ? 'bg-red-50 border-red-200 text-red-700'
                : isGenerating ? 'bg-blue-50 border-blue-100 text-blue-800'
                : contenu ? 'bg-green-50 border-green-200 text-green-800'
                : 'bg-gray-50 border-gray-200 text-gray-500')}>
              <span className="text-base leading-none mt-0.5">{av.icone}</span>
              <div className="min-w-0">
                <p className="font-medium flex items-center gap-2">
                  {av.texte}
                  {isGenerating && <LoadingSpinner size={12} />}
                </p>
                {av.sousTexte && <p className="text-xs mt-0.5 opacity-80 break-words">{av.sousTexte}</p>}
              </div>
            </div>

            {!isGenerating && !contenu && !error && (
              <div className="mt-auto bg-blue-50 border border-blue-100 rounded-lg p-3 text-xs text-blue-800">
                <strong>Prochaine étape :</strong>{' '}
                {!isWiki && selectedIds.size === 0
                  ? 'sélectionnez des documents (liste « Documents du rapport » ou Assistant).'
                  : !prompt.trim()
                  ? (isWiki ? 'décrivez le tuto à rédiger dans « Instructions ».' : 'décrivez le rapport à générer dans « Instructions ».')
                  : 'cliquez sur « Générer » en bas.'}
              </div>
            )}
            {contenu && !isGenerating && (
              <button type="button" onClick={() => setMode('rendu')}
                className="mt-auto text-xs px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 self-start">
                Voir le rendu →
              </button>
            )}
          </div>
        )}

        {/* ── RENDU : document rendu en streaming ── */}
        {mode === 'rendu' && (
          isGenerating && !contenu ? (
            <div className="flex items-center justify-center h-full">
              <LoadingSpinner label="Le modèle réfléchit… (rédaction imminente)" />
            </div>
          ) : contenu ? (
            <div className="p-4">
              <div className="prose prose-sm max-w-none prose-headings:font-semibold prose-headings:text-gray-800 prose-p:text-gray-700 prose-li:text-gray-700">
                <ReactMarkdown>{contenu}</ReactMarkdown>
                {isGenerating && <span className="inline-block w-1 h-4 bg-blue-500 animate-pulse ml-0.5 align-middle" />}
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-xs text-gray-400">Aucun rendu pour l'instant.</div>
          )
        )}

        {/* ── SOURCE : Markdown brut ── */}
        {mode === 'source' && contenu && (
          <div className="p-4">
            <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono leading-relaxed">
              {contenu}
              {isGenerating && <span className="animate-pulse">▌</span>}
            </pre>
          </div>
        )}

        {/* ── ÉDITER : édition inline ── */}
        {mode === 'edit' && contenu && (
          <textarea
            value={contenu}
            onChange={e => editRapport(e.target.value)}
            spellCheck={false}
            aria-label="Éditer le contenu Markdown"
            placeholder="Contenu Markdown…"
            className="w-full h-full min-h-[400px] p-4 text-xs font-mono leading-relaxed text-gray-700 outline-none resize-none bg-white"
          />
        )}

        {/* ── HISTORIQUE : rapports archivés (persistants) ── */}
        {mode === 'historique' && <ReportHistory onOuvert={() => setMode('rendu')} />}
      </div>

      <PublishBookStackModal
        isOpen={showPublish}
        onClose={() => setShowPublish(false)}
        defaultTitle={contenu ? titreParDefaut(contenu) : ''}
        markdown={contenu}
      />
    </div>
  )
}
