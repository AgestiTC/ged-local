/**
 * Page Rapports — Parcours guidé (stepper)
 * ========================================
 * Colonne gauche : étapes numérotées (1 Quoi produire · 2 Documents · 3 Instructions · 4 Générer).
 * Seules les étapes pertinentes pour le mode choisi sont affichées.
 * Colonne droite  : résultat (ou progression du comparatif), en grand.
 */
import { useEffect, useState } from 'react'
import { useDocumentStore } from '../stores/documentStore'
import { useReportStore } from '../stores/reportStore'
import { useModeles } from '../hooks/useModeles'
import IndexedDocsTree from '../components/files/IndexedDocsTree'
import PromptEditor from '../components/reports/PromptEditor'
import MusiquePanel from '../components/reports/MusiquePanel'
import ProjetBar from '../components/reports/ProjetBar'
import { useProjetPart, useProjetStore } from '../stores/projetStore'
import ModelSelector from '../components/reports/ModelSelector'
import OutputMode from '../components/reports/OutputMode'
import TemplateUpload from '../components/reports/TemplateUpload'
import GenerateButton from '../components/reports/GenerateButton'
import GenerationEstimate from '../components/reports/GenerationEstimate'
import AssistantInput from '../components/reports/AssistantInput'
import Step from '../components/reports/Step'
import GroupBuilder from '../components/reports/GroupBuilder'
import CritereBuilder from '../components/reports/CritereBuilder'
import ResultPanel from '../components/reports/ResultPanel'
import ChatPanel from '../components/reports/ChatPanel'
import { FolderSearch, Sparkles, Settings2, ChevronDown, Loader2, FileType2, FileText, MessageSquare } from 'lucide-react'
import { clsx } from 'clsx'
import { compareApi, documentsApi, generateApi, suivreJob } from '../api'
import { groupesParDossier, type DocChemin } from '../utils/groupesParDossier'
import { uuid } from '../utils/uuid'
import { useToast } from '../components/common/Toast'
import type { CritereSource, GroupeComparatif } from '../types'

export default function ReportsPage() {
  const { selectedIds, selectMany, deselectAll } = useDocumentStore()
  const { outputMode, model, prompt, setOutputMode, setPrompt, setModel, rapportFinal, loadRapport, jobId } = useReportStore()
  // Chargé au montage de la PAGE (et non du sélecteur, replié par défaut) : résout le modèle
  // « Auto » à afficher et répare une sélection devenue invalide. Cf. bug « mixtral ».
  const infoModeles = useModeles()
  // Modèle réellement appliqué : la sélection, ou le défaut backend quand on est en « Auto ».
  const modelEffectif = model || infoModeles.defaut
  const tailleModele = infoModeles.modeles.find(m => m.name === modelEffectif)?.size
  const toast = useToast()
  const [isFilling, setIsFilling] = useState(false)

  const [selectedTemplateId, setSelectedTemplateId] = useState<string | undefined>()
  const [docTab, setDocTab] = useState<'parcourir' | 'assistant'>('parcourir')
  const [showModele, setShowModele] = useState(false)
  // Mode de la page : produire un rapport (parcours guidé) OU dialoguer librement avec l'IA (chat).
  const [pageMode, setPageMode] = useState<'rapport' | 'chat'>('rapport')

  // État mode comparatif
  const [groupes, setGroupes] = useState<GroupeComparatif[]>([])
  // Critères = colonnes du tableau. 'ia' par défaut : rien à fournir pour démarrer.
  const [critereSource, setCritereSource] = useState<CritereSource>('ia')
  const [criteres, setCriteres] = useState<string[]>([])
  const [compareJobId, setCompareJobId] = useState<string | null>(null)
  const [isComparing, setIsComparing] = useState(false)

  // ── Projet ouvert : chaque morceau de l'état s'y inscrit (sauvegarde auto + reprise) ──
  const rattacher = useProjetStore(s => s.rattacher)
  const setModeCourant = useProjetStore(s => s.setModeCourant)
  useEffect(() => { setModeCourant(outputMode) }, [outputMode, setModeCourant])
  useProjetPart('creer', { mode: outputMode, prompt, model, rapport: rapportFinal }, v => {
    if (v.mode) setOutputMode(v.mode)
    setPrompt(v.prompt ?? '')
    setModel(v.model ?? '')
    if (v.rapport) loadRapport(v.rapport)
  })
  useProjetPart('documents', [...selectedIds], ids => { deselectAll(); if (ids?.length) selectMany(ids) })
  useProjetPart('comparatif', { groupes, critereSource, criteres, selectedTemplateId: selectedTemplateId ?? null }, v => {
    setGroupes(v.groupes ?? [])
    setCritereSource(v.critereSource ?? 'ia')
    setCriteres(v.criteres ?? [])
    setSelectedTemplateId(v.selectedTemplateId ?? undefined)
  })
  // Un rapport terminé dans un projet ouvert s'y rattache (le texte est aussi dans l'état).
  useEffect(() => { if (rapportFinal && jobId) rattacher('job', jobId, 'Rapport') }, [rapportFinal, jobId, rattacher])

  // Remplir un modèle DOCX (tâche durable) → suit le job puis télécharge le fichier produit.
  const remplirTemplate = async () => {
    if (!selectedTemplateId) { toast.error('Sélectionnez un modèle Word (.docx)'); return }
    if (selectedIds.size === 0) { toast.error('Sélectionnez au moins un document'); return }
    setIsFilling(true)
    try {
      const { job_id } = await generateApi.fillTemplate({
        document_ids: [...selectedIds],
        template_id: selectedTemplateId,
        instructions: prompt.trim() || undefined,
        model,
      })
      const job = await suivreJob(job_id)
      if (job.statut === 'completed') {
        rattacher('job', job_id, 'Modèle rempli')
        const a = document.createElement('a')
        a.href = generateApi.fillTemplateDownloadUrl(job_id)
        a.click()
        toast.success('Modèle rempli — téléchargement du .docx')
      } else {
        toast.error(`Remplissage échoué : ${job.erreur ?? 'Ollama ?'}`)
      }
    } catch {
      toast.error('Remplissage impossible (Ollama ?)')
    } finally { setIsFilling(false) }
  }

  const lancerComparaison = async () => {
    if (groupes.length < 2) { toast.error('Ajoutez au moins 2 candidats / sociétés'); return }
    const invalides = groupes.filter(g => !g.nom.trim() || g.document_ids.length === 0)
    if (invalides.length > 0) { toast.error('Chaque groupe doit avoir un nom et au moins un document'); return }
    // Les critères sont FACULTATIFS : seul le mode « template » exige un fichier, parce que
    // ce sont ses en-têtes qui font les colonnes. Sinon : saisie libre, ou déduction par l'IA.
    if (critereSource === 'template' && !selectedTemplateId) {
      toast.error('Sélectionnez un template Excel (ou choisissez un autre mode de critères)')
      return
    }
    const colonnes = criteres.map(c => c.trim()).filter(Boolean)

    setIsComparing(true)
    setCompareJobId(null)
    try {
      const res = await compareApi.start({
        groupes: groupes.map(g => ({ nom: g.nom, document_ids: g.document_ids })),
        template_id: critereSource === 'template' ? selectedTemplateId : undefined,
        colonnes: critereSource === 'template' || colonnes.length === 0 ? undefined : colonnes,
        model,
        instructions: prompt.trim() || undefined,
      })
      setCompareJobId(res.job_id)
    } catch {
      toast.error('Erreur lancement comparaison')
      setIsComparing(false)
    }
  }

  // Grille d'analyse choisie en mode « Remplir un modèle » : on bascule en Tableau comparatif avec
  // la grille comme source des critères, un groupe par dossier de candidat (d'après les documents
  // cochés) et les instructions déjà saisies. Avant (01/10/2026) : bouton grisé, sans explication.
  const repartirSelection = async () => {
    const ids = [...selectedIds]
    const docs = (await Promise.all(ids.map(id =>
      documentsApi.get(id).then(d => ({ id, chemin: d.chemin })).catch(() => null),
    ))).filter((d): d is DocChemin => d !== null)
    const { groupes: trouves, ecartes } = groupesParDossier(docs)
    setGroupes(trouves.map(g => ({ id: uuid(), ...g })))
    if (trouves.length >= 2) {
      toast.success(`${trouves.length} candidats : ${trouves.map(g => g.nom).join(', ')}`
        + (ecartes ? ` — ${ecartes} fichier(s) hors dossier de candidat écarté(s)` : ''))
    } else {
      toast.error('Impossible de répartir les documents par candidat : composez les groupes à la main')
    }
  }

  const passerEnComparatif = async () => {
    setCritereSource('template')
    setOutputMode('comparatif')      // les instructions suivent : même champ dans tous les modes
    await repartirSelection()
  }

  const isComparatif = outputMode === 'comparatif'
  const isTemplate = outputMode === 'remplir_template'
  const isWiki = outputMode === 'wiki'

  // Étapes « Documents » et « Sujet / Instructions » extraites en sous-rendus pour pouvoir les
  // RÉORDONNER : en mode wiki, le sujet du tuto passe AVANT les documents (optionnels).
  // (Plus de numérotation : le repère d'étape est neutre, le titre porte le nom — cf. Step.tsx.)
  const renderDocsStep = () => (
    <Step
      title={isWiki ? 'Documents sources (optionnel)' : 'Quels documents ?'}
      hint={isWiki
        ? (selectedIds.size > 0
            ? `${selectedIds.size} document${selectedIds.size > 1 ? 's' : ''} comme appui.`
            : 'Facultatif — appuie-toi sur des documents indexés, ou rédige le tuto from scratch.')
        : (selectedIds.size > 0
            ? `${selectedIds.size} document${selectedIds.size > 1 ? 's' : ''} sélectionné${selectedIds.size > 1 ? 's' : ''}.`
            : 'Coche des fichiers — ou laisse l\'Assistant les proposer.')}
    >
      {/* Onglets de choix */}
      <div className="flex rounded-lg border border-gray-200 p-0.5 mb-3 bg-gray-50 text-xs">
        {([
          { key: 'parcourir', label: 'Parcourir', Icon: FolderSearch },
          { key: 'assistant', label: 'Assistant IA', Icon: Sparkles },
        ] as const).map(({ key, label, Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setDocTab(key)}
            className={clsx(
              'flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md font-medium transition-colors',
              docTab === key ? 'bg-white text-blue-700 shadow-sm' : 'text-gray-500 hover:text-gray-700',
            )}
          >
            <Icon size={13} /> {label}
          </button>
        ))}
      </div>

      {docTab === 'parcourir'
        ? <div className="h-[340px]"><IndexedDocsTree /></div>
        : <AssistantInput />}
    </Step>
  )

  const renderPromptStep = () => (
    <Step
      title={isWiki ? 'Sujet / consignes du tuto' : 'Instructions'}
      hint={isWiki
        ? 'Décris le tuto à rédiger — l\'IA produit le Markdown (publiable sur le wiki).'
        : isComparatif
          ? 'Décris comment comparer : ce qui compte, ce qu\'il faut faire ressortir, comment trancher.'
          : outputMode === 'classement'
            ? 'Décris les critères de classement ou de tri à appliquer aux documents.'
            : 'Décris ce que l\'IA doit produire à partir des documents.'}
    >
      {/* Même bloc partout (presets, sauvegarde, modèle). En comparatif, c'est ICI que se donnent
          les consignes de la comparaison : avant, une zone de 2 lignes « optionnel », sans
          prompts enregistrés ni choix du modèle. */}
      <PromptEditor placeholder={isComparatif
        ? 'Décrivez la comparaison à mener…\n\nExemples :\n• Compare les offres sur le prix, les délais et les garanties\n• Mets en valeur les points différenciants, avec des chiffres précis\n• Signale ce qui manque dans chaque dossier'
        : outputMode === 'classement'
          ? 'Décrivez le classement à produire…\n\nExemples :\n• Classe les candidats par années d\'expérience\n• Trie les offres de la moins chère à la plus chère\n• Note chaque dossier sur 10 et justifie'
          : undefined} />

      {/* Modèle — réglage avancé replié par défaut */}
      <button
        type="button"
        onClick={() => setShowModele(v => !v)}
        className="mt-3 flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700"
      >
        <Settings2 size={13} />
        Modèle IA{' '}
        <span className="text-gray-400">
          {/* « Auto » = aucun modèle imposé → on affiche celui que le backend appliquera.
              Ne jamais afficher une valeur figée côté front : c'était le bug « mixtral ». */}
          ({model ? model.split(':')[0] : `Auto${infoModeles.defaut ? ` : ${infoModeles.defaut.split(':')[0]}` : ''}`})
        </span>
        <ChevronDown size={13} className={clsx('transition-transform', showModele && 'rotate-180')} />
      </button>
      {showModele && <div className="mt-2"><ModelSelector {...infoModeles} /></div>}
    </Step>
  )

  return (
    // Sur mobile : hauteur naturelle, la page défile. Sur lg+ : hauteur fixe, colonnes à
    // défilement interne (mise en page bureau conservée).
    <div className="flex flex-col gap-3 p-2 sm:p-3 lg:h-full lg:overflow-hidden">

      {/* Bascule : produire un rapport (guidé) ⇆ dialoguer librement avec l'IA */}
      <div className="flex rounded-lg border border-gray-200 p-0.5 bg-gray-50 text-sm self-start">
        {([
          { key: 'rapport', label: 'Rapport / document', Icon: FileText },
          { key: 'chat', label: 'Discuter avec l\'IA', Icon: MessageSquare },
        ] as const).map(({ key, label, Icon }) => (
          <button key={key} type="button" onClick={() => setPageMode(key)}
            className={clsx('flex items-center gap-1.5 px-3 py-1.5 rounded-md font-medium transition-colors',
              pageMode === key ? 'bg-white text-violet-700 shadow-sm' : 'text-gray-500 hover:text-gray-700')}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {pageMode === 'chat' ? (
        <div className="flex-1 min-h-0"><ChatPanel /></div>
      ) : (
      <>
      {/* Projet : commencer, reprendre, archiver — quelle que soit la tuile */}
      <ProjetBar onOuvert={mode => setOutputMode(mode as typeof outputMode)} />

      {/* ① Que veux-tu produire ? — barre pleine largeur */}
      <Step title="Que veux-tu produire ?" hint="Choisis la destination — la suite s'adapte." last>
        <OutputMode />
      </Step>

      {/* Corps : configuration + résultat — EMPILÉS sous lg, côte à côte au-delà. */}
      {outputMode === 'musique' ? <MusiquePanel /> : (
      <div className="flex flex-col lg:flex-row gap-4 flex-1 min-h-0 lg:overflow-hidden">

        {/* ── Colonne config : parcours guidé ─────────────────── */}
        <section className="w-full lg:w-[460px] shrink-0 flex flex-col gap-3 lg:overflow-y-auto pr-1 pb-2">

        {isComparatif ? (
          <>
            {/* Même arborescence qu'ailleurs : on y coche les dossiers des candidats, puis on les
                répartit en groupes (avant, seule une recherche par nom sur 500 documents). */}
            {renderDocsStep()}

            {/* ② Candidats / Sociétés — AVANT les critères : l'IA en a besoin pour les proposer. */}
            <Step title="Candidats / Sociétés" hint="Un groupe de documents par élément à comparer (1 contrat = 1 groupe).">
              <GroupBuilder
                groupes={groupes}
                onChange={setGroupes}
                selectionIds={[...selectedIds]}
                onRepartir={repartirSelection}
              />
            </Step>

            {/* ③ Instructions — AVANT les critères : elles orientent ceux que l'IA propose, puis
                l'extraction, l'évaluation de chaque critère et la synthèse. */}
            {renderPromptStep()}

            {/* ④ Critères de comparaison — FACULTATIFS (IA, saisie ou template Excel) */}
            <Step title="Critères de comparaison" hint="Les colonnes du tableau. Rien à fournir : l'IA les déduit.">
              <CritereBuilder
                source={critereSource}
                onSourceChange={setCritereSource}
                colonnes={criteres}
                onColonnesChange={setCriteres}
                templateId={selectedTemplateId}
                onTemplateChange={setSelectedTemplateId}
                documentIds={groupes.flatMap(g => g.document_ids.slice(0, 2))}
                instructions={prompt}
                model={model}
              />
            </Step>
          </>
        ) : (
          <>
            {/* Bandeau d'aide en mode « Tuto wiki » */}
            {isWiki && (
              <div className="rounded-lg bg-purple-50 border border-purple-100 p-3 text-xs text-purple-800 leading-relaxed">
                <strong>📖 Tuto wiki</strong> — décris ton tuto dans <strong>« Sujet / consignes »</strong>{' '}
                (les documents sont optionnels), puis <strong>Générer</strong>. Le résultat est éditable, et
                la <strong>publication sur le wiki reste manuelle</strong> (bouton « Publier sur le wiki »).
              </div>
            )}

            {/* Template DOCX (mode « remplir un template » uniquement) */}
            {isTemplate && (
              <Step title="Modèle à remplir" hint="Un fichier Word (.docx) à trous {{champ}} — ou une grille d'analyse Excel.">
                <TemplateUpload
                  selectedTemplateId={selectedTemplateId}
                  onSelect={setSelectedTemplateId}
                  onUtiliserGrille={passerEnComparatif}
                />
              </Step>
            )}

            {/* En wiki : Sujet (②) AVANT Documents (③). Sinon : Documents puis Instructions. */}
            {isWiki ? (
              <>
                {renderPromptStep()}
                {renderDocsStep()}
              </>
            ) : (
              <>
                {renderDocsStep()}
                {renderPromptStep()}
              </>
            )}
          </>
        )}

        {/* Étape finale — Générer */}
        <Step title="Générer" accent last>
          {isComparatif ? (
            <button
              type="button"
              onClick={lancerComparaison}
              disabled={isComparing}
              className="w-full py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-semibold rounded-xl text-sm transition-colors"
            >
              {isComparing ? 'Analyse en cours…' : 'Générer le tableau comparatif'}
            </button>
          ) : isTemplate ? (
            <button
              type="button"
              onClick={remplirTemplate}
              disabled={isFilling || !selectedTemplateId || selectedIds.size === 0}
              className="w-full flex items-center justify-center gap-2 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-100 disabled:text-gray-400 text-white font-semibold rounded-xl text-sm transition-colors"
            >
              {isFilling ? <Loader2 size={15} className="animate-spin" /> : <FileType2 size={15} />}
              {isFilling ? 'Remplissage…'
                : !selectedTemplateId ? 'Choisissez un modèle .docx'
                : selectedIds.size === 0 ? 'Sélectionnez des documents'
                : `Remplir et télécharger (${selectedIds.size} doc${selectedIds.size > 1 ? 's' : ''})`}
            </button>
          ) : (
            <div className="flex flex-col gap-2">
              <GenerationEstimate modelEffectif={modelEffectif} tailleOctets={tailleModele} />
              <GenerateButton />
            </div>
          )}
        </Step>
        </section>

        {/* ── Colonne droite : panneau « Résultat » — hauteur minimale sur mobile (empilé). ── */}
        <div className="flex-1 min-w-0 flex min-h-[60vh] lg:min-h-0">
          <ResultPanel
            isComparatif={isComparatif}
            compareJobId={compareJobId}
            groupeNoms={groupes.map(g => g.nom)}
            onComparatifComplete={() => {
              if (compareJobId) rattacher('job', compareJobId, 'Tableau comparatif')
              setIsComparing(false)
              toast.success('Tableau comparatif prêt — choisissez le format à télécharger')
            }}
            onComparatifError={(msg) => {
              setIsComparing(false)
              setCompareJobId(null)
              toast.error(msg)
            }}
          />
        </div>

      </div>
      )}
      </>
      )}
    </div>
  )
}
