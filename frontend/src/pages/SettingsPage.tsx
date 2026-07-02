/**
 * Page Paramètres — Configuration des dossiers surveillés, prompts, templates, stats, services
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useDropzone } from 'react-dropzone'
import {
  AlertTriangle, BookOpen, Bot, CheckCircle, Database, Download,
  Edit2, FileText, Globe, HardDrive, Landmark, MessageSquare, Plus, RefreshCw,
  Save, Search, Trash2, Upload, X, XCircle,
  type LucideIcon,
} from 'lucide-react'
import { clsx } from 'clsx'
import { foldersApi, systemApi, statsApi, uploadApi, promptsApi, templatesApi, documentsApi, type DocumentStats, type ConfigUpdate, type OllamaModel } from '../api'
import { useToast } from '../components/common/Toast'
import LoadingSpinner from '../components/common/LoadingSpinner'
import SourcesManager from '../components/ged/SourcesManager'
import IndexedSourcesSummary from '../components/ged/IndexedSourcesSummary'
import CollapsibleSection from '../components/common/CollapsibleSection'
import type { DossierSurveille, PromptPreset, Template } from '../types'

// ── Helpers ──────────────────────────────────────────────────────────────────

function extractApiError(e: unknown): string {
  if (e && typeof e === 'object') {
    const axiosError = e as { response?: { data?: { detail?: string } }; message?: string }
    if (axiosError.response?.data?.detail) return axiosError.response.data.detail
    if (axiosError.message) return axiosError.message
  }
  return 'Erreur inconnue'
}


function formatBytes(octets: number): string {
  if (octets < 1024) return `${octets} o`
  if (octets < 1024 * 1024) return `${(octets / 1024).toFixed(0)} Ko`
  if (octets < 1024 * 1024 * 1024) return `${(octets / (1024 * 1024)).toFixed(1)} Mo`
  return `${(octets / (1024 * 1024 * 1024)).toFixed(2)} Go`
}

const STATUT_LABELS: Record<string, { label: string; color: string }> = {
  enriched: { label: 'Enrichis', color: 'text-green-600 bg-green-50' },
  extracted: { label: 'Extraits', color: 'text-blue-600 bg-blue-50' },
  pending: { label: 'En attente', color: 'text-yellow-600 bg-yellow-50' },
  error: { label: 'Erreurs', color: 'text-red-600 bg-red-50' },
}

// ── Zone drag & drop documents ────────────────────────────────────────────────

const ACCEPTED_MIME = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx', '.ppsx'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/zip': ['.zip'],
  'application/x-zip-compressed': ['.zip'],
  'application/vnd.oasis.opendocument.text': ['.odt'],
  'application/vnd.oasis.opendocument.spreadsheet': ['.ods'],
  'application/vnd.oasis.opendocument.presentation': ['.odp'],
}

interface UploadDropZoneProps {
  onDone: (nb: number) => void
}

function UploadDropZone({ onDone }: UploadDropZoneProps) {
  const toast = useToast()
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)

  const onDrop = useCallback(async (files: File[]) => {
    if (files.length === 0) return
    setUploading(true)
    setProgress(0)
    try {
      await uploadApi.uploadFiles(files, pct => setProgress(pct))
      toast.success(`${files.length} fichier(s) soumis à l'indexation`)
      onDone(files.length)
    } catch (e) {
      toast.error(extractApiError(e))
    } finally {
      setUploading(false)
      setProgress(0)
    }
  }, [toast, onDone])

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    accept: ACCEPTED_MIME,
    multiple: true,
    disabled: uploading,
  })

  return (
    <div
      {...getRootProps()}
      className={[
        'relative flex flex-col items-center justify-center gap-2 p-5 rounded-xl border-2 border-dashed cursor-pointer transition-all select-none',
        isDragActive && !isDragReject ? 'border-blue-400 bg-blue-50 scale-[1.01]' : '',
        isDragReject ? 'border-red-400 bg-red-50' : '',
        !isDragActive && !isDragReject ? 'border-gray-200 hover:border-blue-300 hover:bg-gray-50' : '',
        uploading ? 'opacity-60 cursor-not-allowed' : '',
      ].join(' ')}
    >
      <input {...getInputProps()} />

      <div className={`p-2.5 rounded-full ${isDragActive ? 'bg-blue-100' : 'bg-gray-100'}`}>
        {uploading ? (
          <LoadingSpinner size={20} />
        ) : (
          <Upload size={20} className={isDragActive ? 'text-blue-500' : 'text-gray-400'} />
        )}
      </div>

      <div className="text-center">
        {isDragReject && <p className="text-sm font-medium text-red-600">Format non supporté</p>}
        {isDragActive && !isDragReject && <p className="text-sm font-medium text-blue-600">Relâchez pour importer</p>}
        {!isDragActive && !uploading && (
          <>
            <p className="text-sm font-medium text-gray-700">Glissez vos documents ici</p>
            <p className="text-xs text-gray-400 mt-0.5">ou cliquez pour parcourir</p>
          </>
        )}
        {uploading && <p className="text-sm text-gray-500">Import en cours… {progress}%</p>}
      </div>

      <p className="text-xs text-gray-400">PDF · DOCX · PPTX · XLSX · ZIP · ODT</p>

      {/* Barre de progression */}
      {uploading && (
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-gray-100 rounded-b-xl overflow-hidden">
          <div
            className="h-full bg-blue-400 transition-all duration-200"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </div>
  )
}

// ── Page principale ───────────────────────────────────────────────────────────

// ── Catégories de prompts ─────────────────────────────────────────────────────

const CATEGORIES_PROMPT: Record<string, string> = {
  rapport: 'Rapport',
  classement: 'Classement',
  extraction: 'Extraction',
  analyse: 'Analyse',
}

// ── Formulaire de prompt ──────────────────────────────────────────────────────

interface PromptFormData {
  nom: string
  description: string
  prompt_text: string
  categorie: string
  modele_prefere: string
}

const PROMPT_VIDE: PromptFormData = { nom: '', description: '', prompt_text: '', categorie: '', modele_prefere: '' }

/**
 * Recommande, parmi les modèles INSTALLÉS, le meilleur pour chaque rôle — 100% local
 * (heuristiques nom + taille, aucun réseau). `update === null` = hors registre (import perso).
 */
type ModeleLite = { name: string; size: number; update?: boolean | null }
function recommanderModeles(models: ModeleLite[]) {
  const E = models.map(m => {
    const n = m.name.toLowerCase()
    return {
      name: m.name,
      gb: m.size / 1e9,
      embed: /embed/.test(n),
      vision: /(^|[^a-z])vl([^a-z]|$)|vision|llava|ocr|minicpm-v|moondream|qwen2\.?5vl/.test(n),
      creatif: /abliterat|dolphin|uncensored|uncensured|mythos|roleplay|(^|[^a-z])rp([^a-z]|$)/.test(n) || m.update === null,
    }
  })
  const textes = E.filter(m => !m.embed && !m.vision)
  const parGrand = (a: typeof E[0], b: typeof E[0]) => b.gb - a.gb
  const parPetit = (a: typeof E[0], b: typeof E[0]) => a.gb - b.gb
  const first = <T,>(arr: T[]) => (arr.length ? arr[0] : null)
  return {
    raisonnement: first([...textes].sort(parGrand)),
    rapide: first([...textes.filter(m => m.gb >= 3 && m.gb <= 14 && !m.creatif)].sort(parPetit)) ?? first([...textes].sort(parPetit)),
    embeddings: first([...E.filter(m => m.embed)].sort(parGrand)),
    vision: first([...E.filter(m => m.vision)].sort(parGrand)),
    creatif: first([...E.filter(m => m.creatif && !m.embed && !m.vision)].sort(parGrand)),
  }
}

// ── Sections de la page (accès rapide + recherche) ────────────────────────────
// L'ordre correspond à l'ordre de rendu des CollapsibleSection ci-dessous.
const SETTINGS_SECTIONS: { id: string; title: string; Icon: LucideIcon; color: string; defaultOpen?: boolean }[] = [
  { id: 'set-sources',     title: 'Sources & indexation',             Icon: Database,      color: 'text-blue-600',   defaultOpen: true },
  { id: 'set-generation',  title: 'Génération — prompts & templates', Icon: MessageSquare, color: 'text-amber-600' },
  { id: 'set-stats',       title: 'Statistiques',                     Icon: Database,      color: 'text-blue-600' },
  { id: 'set-maintenance', title: 'Maintenance',                      Icon: AlertTriangle, color: 'text-amber-600' },
  { id: 'set-services',    title: 'Services & modèles IA',            Icon: HardDrive,     color: 'text-gray-600' },
  { id: 'set-internet',    title: 'Demandes Mise à jour internet',    Icon: Globe,         color: 'text-blue-600' },
  { id: 'set-wiki',        title: 'Wiki BookStack',                   Icon: BookOpen,      color: 'text-purple-600' },
  { id: 'set-hf',          title: 'HuggingFace 🤗',                    Icon: Bot,           color: 'text-yellow-500' },
  { id: 'set-admin',       title: 'Administration — liens',           Icon: Landmark,      color: 'text-blue-600' },
  { id: 'set-logs',        title: 'Logs & historique',                Icon: FileText,      color: 'text-gray-600' },
  { id: 'set-apropos',     title: 'À propos',                         Icon: FileText,      color: 'text-gray-500' },
]

// ── Composant principal ───────────────────────────────────────────────────────

export default function SettingsPage() {
  const [dossiers, setDossiers] = useState<DossierSurveille[]>([])
  const [statuts, setStatuts] = useState<{ tika: boolean | null; ollama: boolean | null; n8n: boolean | null; clamav: boolean | null; bookstack: boolean | null }>({ tika: null, ollama: null, n8n: null, clamav: null, bookstack: null })
  const [config, setConfig] = useState<ConfigUpdate>({ tika_url: '', ollama_url: '', n8n_url: '', default_model: '', bookstack_url: '', bookstack_token_id: '', bookstack_token_secret: '', huggingface_token: '', huggingface_user: '', huggingface_password: '', usage_models: '{}', admin_links: '[]' })
  const [savingConfig, setSavingConfig] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [models, setModels] = useState<OllamaModel[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [verifMaj, setVerifMaj] = useState(false)
  // Garde-fou 100% local : toute action qui contacte Internet demande une confirmation.
  const [netConfirm, setNetConfirm] = useState<null | { titre: string; message: string; action: () => void }>(null)
  // Date de la dernière vérif MAJ (persistée en local, sans réseau).
  const [derniereVerif, setDerniereVerif] = useState<string | null>(() => localStorage.getItem('maj_derniere_verif'))
  const [nouveauLien, setNouveauLien] = useState({ section: '', label: '', url: '' })  // form Administration
  const [pulls, setPulls] = useState<Record<string, { status: string; pct: number }>>({})
  const [stats, setStats] = useState<DocumentStats | null>(null)

  // Prompts
  const [prompts, setPrompts] = useState<PromptPreset[]>([])
  const [promptForm, setPromptForm] = useState<PromptFormData>(PROMPT_VIDE)
  const [editingPromptId, setEditingPromptId] = useState<string | null>(null)
  const [showPromptForm, setShowPromptForm] = useState(false)
  const [savingPrompt, setSavingPrompt] = useState(false)

  // Templates
  const [templates, setTemplates] = useState<Template[]>([])
  const [uploadingTemplate, setUploadingTemplate] = useState(false)

  // Maintenance
  const [purgingDoublons, setPurgingDoublons] = useState(false)
  const [reenrichingLot, setReenrichingLot] = useState(false)
  const [analysingLot, setAnalysingLot] = useState(false)
  const [counts, setCounts] = useState<{ reenrich: number; sans_texte: number; medias: number } | null>(null)

  // Accès rapide (grille de sections) + recherche
  const [recherche, setRecherche] = useState('')
  const [openMap, setOpenMap] = useState<Record<string, boolean>>(() => {
    const m: Record<string, boolean> = {}
    for (const s of SETTINGS_SECTIONS) {
      const v = localStorage.getItem(`collapse:${s.id}`)
      m[s.id] = v !== null ? v === '1' : !!s.defaultOpen
    }
    return m
  })
  const sectionMatch = (id: string) => {
    const t = recherche.trim().toLowerCase()
    if (!t) return true
    const s = SETTINGS_SECTIONS.find(x => x.id === id)
    return !!s && s.title.toLowerCase().includes(t)
  }
  // Props communes injectées à chaque CollapsibleSection (ouverture pilotée + filtre recherche)
  const secProps = (id: string) => ({
    open: openMap[id] ?? false,
    onToggle: (n: boolean) => setOpenMap(m => ({ ...m, [id]: n })),
    hidden: !sectionMatch(id),
  })
  const ouvrirSection = (id: string) => {
    setOpenMap(m => ({ ...m, [id]: true }))
    localStorage.setItem(`collapse:${id}`, '1')
    requestAnimationFrame(() => document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
  const sectionsVisibles = SETTINGS_SECTIONS.filter(s => sectionMatch(s.id))

  const toast = useToast()

  useEffect(() => {
    foldersApi.list().then(d => setDossiers(d.dossiers)).catch(() => {})
    systemApi.services().then(s => setStatuts({ tika: s.tika.ok, ollama: s.ollama.ok, n8n: s.n8n?.ok ?? false, clamav: s.clamav?.ok ?? false, bookstack: s.bookstack?.ok ?? false }))
      .catch(() => setStatuts({ tika: false, ollama: false, n8n: false, clamav: false, bookstack: false }))
    systemApi.getConfig().then(c => setConfig({
      tika_url: c.tika_url.valeur, ollama_url: c.ollama_url.valeur,
      n8n_url: c.n8n_url.valeur, default_model: c.default_model.valeur,
      bookstack_url: c.bookstack_url?.valeur ?? '',
      bookstack_token_id: c.bookstack_token_id?.valeur ?? '',
      // Les secrets sont masqués côté backend ; on laisse le champ vide (placeholder « défini »).
      bookstack_token_secret: '',
      huggingface_user: c.huggingface_user?.valeur ?? '',
      huggingface_token: '',
      huggingface_password: '',
      usage_models: c.usage_models?.valeur ?? '{}',
      admin_links: c.admin_links?.valeur ?? '[]',
    })).catch(() => {})
    // Chargement local uniquement (pas d'appel réseau). Le badge « officiel/😈 » se renseigne
    // via le bouton « Vérifier les MAJ » (seul moment où l'on contacte le registre Ollama).
    chargerModeles()
    statsApi.getDocumentStats().then(setStats).catch(() => {})
    documentsApi.maintenanceCounts().then(setCounts).catch(() => {})
    promptsApi.list().then(d => setPrompts(d.prompts ?? [])).catch(() => {})
    templatesApi.list().then(d => setTemplates(d.templates ?? [])).catch(() => {})
  }, [])

  async function chargerModeles(checkUpdates = false) {
    if (checkUpdates) setVerifMaj(true); else setLoadingModels(true)
    try {
      const r = await systemApi.models(checkUpdates)
      setModels(r.models)
      if (checkUpdates) {
        const now = new Date().toISOString()
        localStorage.setItem('maj_derniere_verif', now)  // local uniquement
        setDerniereVerif(now)
      }
    } catch {
      setModels([])
    } finally {
      setLoadingModels(false)
      setVerifMaj(false)
    }
  }

  const mettreAJourModele = async (name: string) => {
    setPulls(p => ({ ...p, [name]: { status: 'démarrage…', pct: 0 } }))
    try {
      await systemApi.pullModel(name, prog => {
        if (prog.error) throw new Error(prog.error)
        const pct = prog.total ? Math.round(((prog.completed ?? 0) / prog.total) * 100) : 0
        setPulls(p => ({ ...p, [name]: { status: prog.status, pct } }))
      })
      toast.success(`${name} : à jour`)
      await chargerModeles(true)
    } catch {
      toast.error(`Échec mise à jour ${name}`)
    } finally {
      setPulls(p => { const n = { ...p }; delete n[name]; return n })
    }
  }

  // Test HuggingFace = appel réseau (whoami) → toujours via confirmation (netConfirm).
  const testerHF = async () => {
    setTesting('huggingface')
    try {
      const r = await systemApi.testService('huggingface', config)
      r.ok
        ? toast.success(`HuggingFace OK — connecté en tant que « ${r.user ?? '?'} »`)
        : toast.error(`HuggingFace : ${r.erreur ?? 'échec'}`)
    } catch {
      toast.error('Test HuggingFace échoué')
    } finally {
      setTesting(null)
    }
  }

  const testerService = async (service: 'tika' | 'ollama' | 'n8n' | 'bookstack') => {
    setTesting(service)
    try {
      const r = await systemApi.testService(service, config)   // teste les valeurs saisies (avant sauvegarde)
      setStatuts(s => ({ ...s, [service]: r.ok }))
      r.ok ? toast.success(`${service} : connexion OK`) : toast.error(`${service} : injoignable (${r.url})`)
    } catch {
      toast.error(`Test ${service} échoué`)
    } finally {
      setTesting(null)
    }
  }

  const sauvegarderConfig = async () => {
    setSavingConfig(true)
    try {
      await systemApi.updateConfig(config)
      toast.success('Configuration enregistrée')
      // Re-vérifie les statuts et recharge les modèles avec les nouvelles URLs
      const s = await systemApi.services()
      setStatuts({ tika: s.tika.ok, ollama: s.ollama.ok, n8n: s.n8n?.ok ?? false, clamav: s.clamav?.ok ?? false, bookstack: s.bookstack?.ok ?? false })
      chargerModeles()
    } catch (e) {
      toast.error(extractApiError(e))
    } finally {
      setSavingConfig(false)
    }
  }

  const supprimerDossier = async (id: string) => {
    try {
      await foldersApi.remove(id)
      setDossiers(prev => prev.filter(d => d.id !== id))
      toast.success('Dossier retiré de la surveillance')
    } catch {
      toast.error('Erreur suppression dossier')
    }
  }

  const scannerDossier = async (id: string) => {
    try {
      await foldersApi.scan(id)
      toast.info('Scan lancé en arrière-plan')
    } catch {
      toast.error('Erreur lancement du scan')
    }
  }

  const toggleActif = async (d: DossierSurveille) => {
    try {
      const mis = await foldersApi.update(d.id, { actif: !d.actif })
      setDossiers(prev => prev.map(x => x.id === d.id ? mis : x))
    } catch {
      toast.error('Erreur mise à jour')
    }
  }

  // ── Handlers prompts ────────────────────────────────────────────────────────

  const ouvrirNouveauPrompt = () => {
    setEditingPromptId(null)
    setPromptForm(PROMPT_VIDE)
    setShowPromptForm(true)
  }

  const ouvrirEditionPrompt = (p: PromptPreset) => {
    setEditingPromptId(p.id)
    setPromptForm({
      nom: p.nom,
      description: p.description ?? '',
      prompt_text: p.prompt_text,
      categorie: p.categorie ?? '',
      modele_prefere: p.modele_prefere ?? '',
    })
    setShowPromptForm(true)
  }

  const sauvegarderPrompt = async () => {
    if (!promptForm.nom.trim() || !promptForm.prompt_text.trim()) {
      toast.error('Le nom et le texte du prompt sont requis')
      return
    }
    setSavingPrompt(true)
    const payload = {
      nom: promptForm.nom.trim(),
      description: promptForm.description.trim() || undefined,
      prompt_text: promptForm.prompt_text,
      categorie: (promptForm.categorie || undefined) as PromptPreset['categorie'],
      modele_prefere: promptForm.modele_prefere.trim() || undefined,
    }
    try {
      if (editingPromptId) {
        const mis = await promptsApi.update(editingPromptId, payload)
        setPrompts(prev => prev.map(p => p.id === editingPromptId ? mis : p))
        toast.success('Prompt mis à jour')
      } else {
        const cree = await promptsApi.create(payload)
        setPrompts(prev => [...prev, cree])
        toast.success('Prompt créé')
      }
      setShowPromptForm(false)
      setPromptForm(PROMPT_VIDE)
      setEditingPromptId(null)
    } catch (e) {
      toast.error(extractApiError(e))
    } finally {
      setSavingPrompt(false)
    }
  }

  const supprimerPrompt = async (id: string) => {
    try {
      await promptsApi.delete(id)
      setPrompts(prev => prev.filter(p => p.id !== id))
      if (editingPromptId === id) { setShowPromptForm(false); setEditingPromptId(null) }
      toast.success('Prompt supprimé')
    } catch {
      toast.error('Erreur suppression prompt')
    }
  }

  // ── Handlers templates ──────────────────────────────────────────────────────

  const uploaderTemplate = async (file: File) => {
    setUploadingTemplate(true)
    try {
      const tpl = await templatesApi.upload(file)
      setTemplates(prev => [...prev, tpl])
      toast.success(`Template "${tpl.nom}" ajouté`)
    } catch (e) {
      toast.error(extractApiError(e))
    } finally {
      setUploadingTemplate(false)
    }
  }

  const purgerDoublons = async () => {
    setPurgingDoublons(true)
    try {
      const res = await documentsApi.purgeDoublons()
      toast.success(res.message)
      statsApi.getDocumentStats().then(setStats).catch(() => {})
    } catch (e) {
      toast.error(extractApiError(e))
    } finally {
      setPurgingDoublons(false)
    }
  }

  const rafraichirMaintenance = () => {
    statsApi.getDocumentStats().then(setStats).catch(() => {})
    documentsApi.maintenanceCounts().then(setCounts).catch(() => {})
  }

  // Relance l'IA (durable) sur les documents extraits AVEC texte mais non enrichis.
  const reenrichLot = async () => {
    setReenrichingLot(true)
    try {
      const res = await documentsApi.reenrichBatch()
      toast.success(res.message)
      rafraichirMaintenance()
    } catch (e) {
      toast.error(extractApiError(e))
    } finally {
      setReenrichingLot(false)
    }
  }

  // Ré-analyse le CONTENU (durable) des documents SANS texte (Tika/fetch SMB, zéro doublon).
  const analyserLot = async () => {
    setAnalysingLot(true)
    try {
      const res = await documentsApi.analyzeBatch('empty')
      toast.success(res.message)
      rafraichirMaintenance()
    } catch (e) {
      toast.error(extractApiError(e))
    } finally {
      setAnalysingLot(false)
    }
  }

  // Compteurs réels (via /documents/maintenance/counts).
  const nonAnalyses = counts?.reenrich ?? 0   // extraits AVEC texte, non enrichis → relance IA
  const sansTexte = counts?.sans_texte ?? 0   // extraits/erreur SANS texte → ré-analyse contenu

  const supprimerTemplate = async (id: string) => {
    try {
      await templatesApi.delete(id)
      setTemplates(prev => prev.filter(t => t.id !== id))
      toast.success('Template supprimé')
    } catch {
      toast.error('Erreur suppression template')
    }
  }

  return (
    <div className="max-w-5xl mx-auto p-6 flex flex-col gap-3">

      {/* En-tête : recherche + accès rapide (grille responsive 2/3/4 colonnes) */}
      <div>
        <h1 className="text-lg font-bold text-gray-800 mb-2">Paramètres</h1>
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="search"
            value={recherche}
            onChange={e => setRecherche(e.target.value)}
            placeholder="Rechercher une section (ex. modèles, doublons, wiki, logs…)"
            className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 mt-3">
          {sectionsVisibles.map(s => (
            <button
              key={s.id}
              type="button"
              onClick={() => ouvrirSection(s.id)}
              className="flex items-center gap-2 p-3 bg-white border border-gray-200 rounded-lg hover:border-blue-300 hover:bg-blue-50/40 text-left transition-colors"
            >
              <s.Icon size={16} className={clsx('shrink-0', s.color)} />
              <span className="text-sm font-medium text-gray-700 truncate">{s.title}</span>
            </button>
          ))}
          {sectionsVisibles.length === 0 && (
            <p className="col-span-full text-sm text-gray-400 py-2">Aucune section ne correspond à « {recherche} ».</p>
          )}
        </div>
      </div>

      <CollapsibleSection {...secProps('set-sources')} id="set-sources" icon={<Database size={16} className="text-blue-600" />} title="Sources & indexation">
       <div className="flex flex-col gap-6 pt-1">

      {/* ── Import direct de documents ────────────────────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-1">Import direct</h2>
        <p className="text-xs text-gray-400 mb-3">
          Glissez-déposez des documents pour les indexer immédiatement, sans passer par un dossier surveillé.
        </p>
        <UploadDropZone onDone={() => statsApi.getDocumentStats().then(setStats).catch(() => {})} />
      </section>

      {/* ── Sources de fichiers (local / NAS SMB) ─────────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-1">Sources de fichiers</h2>
        <p className="text-xs text-gray-500 mb-3">
          Déclare ton NAS (ou un autre serveur), liste ses partages, et indexe les dossiers
          choisis. Les identifiants sont chiffrés en base.
        </p>
        <SourcesManager />
      </section>

      {/* ── Dossiers indexés (par source) ────────────────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-1">Dossiers indexés</h2>
        <p className="text-xs text-gray-500 mb-3">
          Ce qui est <strong>réellement dans la GED</strong>, par source. Bouton <strong>« Gérer »</strong>
          pour ouvrir l'arbre et <strong>retirer des dossiers de l'index</strong> (les fichiers du NAS
          ne sont pas supprimés). Pour indexer, passe par <strong>« Sources de fichiers »</strong> ci-dessus.
        </p>

        <IndexedSourcesSummary />

        {/* Surveillance automatique — affichée seulement si des dossiers sont surveillés */}
        {dossiers.length > 0 && (
          <div className="mt-5">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              Surveillance automatique (scan périodique)
            </h3>
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              {dossiers.map((d, i) => (
                <div
                  key={d.id}
                  className={`flex items-center gap-3 px-4 py-3 ${i > 0 ? 'border-t border-gray-100' : ''}`}
                >
                  <button
                    onClick={() => toggleActif(d)}
                    className={`w-2.5 h-2.5 rounded-full shrink-0 transition-colors ${d.actif ? 'bg-green-400' : 'bg-gray-300'}`}
                    title={d.actif ? 'Actif — cliquer pour désactiver' : 'Inactif — cliquer pour activer'}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">{d.nom_affichage || d.chemin}</p>
                    {d.nom_affichage && (
                      <p className="text-xs text-gray-400 truncate font-mono">{d.chemin}</p>
                    )}
                    {d.dernier_scan && (
                      <p className="text-xs text-gray-400">
                        Dernier scan : {new Date(d.dernier_scan).toLocaleString('fr-FR')}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => scannerDossier(d.id)}
                      title="Forcer un scan immédiat"
                      className="p-1.5 text-gray-400 hover:text-blue-500 hover:bg-blue-50 rounded-md transition-colors"
                    >
                      <RefreshCw size={14} />
                    </button>
                    <button
                      onClick={() => supprimerDossier(d.id)}
                      title="Retirer de la surveillance"
                      className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-2">
              ↻ force un scan · ● active/désactive la surveillance.
            </p>
          </div>
        )}
      </section>

       </div>
      </CollapsibleSection>

      <CollapsibleSection {...secProps('set-generation')} id="set-generation" icon={<MessageSquare size={16} className="text-amber-600" />} title="Génération — prompts & templates">
       <div className="flex flex-col gap-6 pt-1">

      {/* ── Prompts pré-enregistrés ───────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-gray-800">Prompts pré-enregistrés</h2>
          <button
            onClick={ouvrirNouveauPrompt}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus size={13} />
            Nouveau prompt
          </button>
        </div>

        {/* Formulaire création/édition */}
        {showPromptForm && (
          <div className="bg-white border border-blue-200 rounded-lg p-4 mb-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-700">
                {editingPromptId ? 'Modifier le prompt' : 'Nouveau prompt'}
              </h3>
              <button onClick={() => setShowPromptForm(false)} className="text-gray-400 hover:text-gray-600">
                <X size={14} />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Nom *</label>
                <input
                  type="text"
                  value={promptForm.nom}
                  onChange={e => setPromptForm(f => ({ ...f, nom: e.target.value }))}
                  placeholder="Ex: Synthèse de contrat"
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Catégorie</label>
                <select
                  value={promptForm.categorie}
                  onChange={e => setPromptForm(f => ({ ...f, categorie: e.target.value }))}
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
                >
                  <option value="">— Aucune —</option>
                  {Object.entries(CATEGORIES_PROMPT).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Description</label>
              <input
                type="text"
                value={promptForm.description}
                onChange={e => setPromptForm(f => ({ ...f, description: e.target.value }))}
                placeholder="Description courte (optionnel)"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Texte du prompt *</label>
              <textarea
                value={promptForm.prompt_text}
                onChange={e => setPromptForm(f => ({ ...f, prompt_text: e.target.value }))}
                rows={5}
                placeholder="Écrivez le prompt ici…"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-blue-400 resize-y font-mono"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Modèle préféré</label>
              <input
                type="text"
                value={promptForm.modele_prefere}
                onChange={e => setPromptForm(f => ({ ...f, modele_prefere: e.target.value }))}
                placeholder="Ex: mixtral:latest (optionnel)"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
            </div>
            <div className="flex gap-2 pt-1">
              <button
                onClick={sauvegarderPrompt}
                disabled={savingPrompt}
                className="flex items-center gap-1.5 text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors font-medium"
              >
                <Save size={13} />
                {savingPrompt ? 'Sauvegarde…' : 'Sauvegarder'}
              </button>
              <button
                onClick={() => setShowPromptForm(false)}
                className="text-xs px-3 py-2 text-gray-500 hover:bg-gray-100 rounded-lg"
              >
                Annuler
              </button>
            </div>
          </div>
        )}

        {/* Liste des prompts */}
        {prompts.length === 0 ? (
          <div className="bg-white border border-dashed border-gray-200 rounded-lg p-6 text-center">
            <MessageSquare size={20} className="text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-400">Aucun prompt enregistré</p>
            <p className="text-xs text-gray-300 mt-1">Créez des prompts réutilisables pour vos rapports</p>
          </div>
        ) : (
          <div className="space-y-2">
            {prompts.map(p => (
              <div
                key={p.id}
                className="bg-white border border-gray-200 rounded-lg px-4 py-3 flex items-start gap-3"
              >
                <MessageSquare size={15} className="text-gray-400 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-gray-800">{p.nom}</span>
                    {p.categorie && (
                      <span className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded-full">
                        {CATEGORIES_PROMPT[p.categorie] ?? p.categorie}
                      </span>
                    )}
                    {p.modele_prefere && (
                      <span className="text-xs text-gray-400 font-mono">{p.modele_prefere}</span>
                    )}
                  </div>
                  {p.description && (
                    <p className="text-xs text-gray-400 mt-0.5">{p.description}</p>
                  )}
                  <p className="text-xs text-gray-500 mt-1 font-mono truncate">{p.prompt_text}</p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => ouvrirEditionPrompt(p)}
                    className="p-1.5 text-gray-400 hover:text-blue-500 hover:bg-blue-50 rounded-lg transition-colors"
                    title="Modifier"
                  >
                    <Edit2 size={13} />
                  </button>
                  <button
                    onClick={() => supprimerPrompt(p.id)}
                    className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                    title="Supprimer"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Templates ─────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-gray-800">Templates</h2>
          <label className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
            uploadingTemplate
              ? 'bg-gray-100 text-gray-400'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}>
            {uploadingTemplate ? <LoadingSpinner size={13} /> : <Upload size={13} />}
            {uploadingTemplate ? 'Upload…' : 'Ajouter un template'}
            <input
              type="file"
              className="hidden"
              accept=".docx,.pdf"
              disabled={uploadingTemplate}
              onChange={e => { if (e.target.files?.[0]) uploaderTemplate(e.target.files[0]); e.target.value = '' }}
            />
          </label>
        </div>
        <p className="text-xs text-gray-400 mb-3">
          Templates DOCX ou PDF avec champs <code className="bg-gray-100 px-1 rounded">{'{{ champ }}'}</code> — remplis automatiquement par l'IA.
        </p>

        {templates.length === 0 ? (
          <div className="bg-white border border-dashed border-gray-200 rounded-lg p-6 text-center">
            <FileText size={20} className="text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-400">Aucun template enregistré</p>
            <p className="text-xs text-gray-300 mt-1">Uploadez un fichier DOCX ou PDF pour commencer</p>
          </div>
        ) : (
          <div className="space-y-2">
            {templates.map(t => (
              <div
                key={t.id}
                className="bg-white border border-gray-200 rounded-lg px-4 py-3 flex items-start gap-3"
              >
                <FileText size={15} className="text-gray-400 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-800">{t.nom}</span>
                    <span className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded-full uppercase">
                      {t.type}
                    </span>
                    {t.champs && t.champs.length > 0 && (
                      <span className="text-xs text-gray-400">{t.champs.length} champ{t.champs.length > 1 ? 's' : ''}</span>
                    )}
                  </div>
                  {t.description && (
                    <p className="text-xs text-gray-400 mt-0.5">{t.description}</p>
                  )}
                  {t.champs && t.champs.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {t.champs.map(c => (
                        <code key={c.nom} className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded">
                          {`{{${c.nom}}}`}
                        </code>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => supprimerTemplate(t.id)}
                  className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0"
                  title="Supprimer"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

       </div>
      </CollapsibleSection>

      <CollapsibleSection {...secProps('set-stats')} id="set-stats" icon={<Database size={16} className="text-blue-600" />} title="Statistiques">
       <div className="pt-1">

      {/* ── Statistiques ─────────────────────────────────── */}
      <section>
        {stats === null ? (
          <LoadingSpinner label="Chargement des statistiques…" />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="bg-white border border-gray-200 rounded-lg p-4 flex items-center gap-3">
              <Database size={20} className="text-blue-500 shrink-0" />
              <div>
                <p className="text-2xl font-bold text-gray-800">{stats.total_documents.toLocaleString('fr-FR')}</p>
                <p className="text-xs text-gray-500">Documents indexés</p>
              </div>
            </div>

            <div className="bg-white border border-gray-200 rounded-lg p-4 flex items-center gap-3">
              <HardDrive size={20} className="text-purple-500 shrink-0" />
              <div>
                <p className="text-2xl font-bold text-gray-800">{formatBytes(stats.taille_totale_octets)}</p>
                <p className="text-xs text-gray-500">Volume indexé</p>
              </div>
            </div>

            <div className="bg-white border border-gray-200 rounded-lg p-4 flex items-center gap-3">
              <FileText size={20} className="text-green-500 shrink-0" />
              <div>
                <p className="text-2xl font-bold text-gray-800">
                  {(stats.par_statut['enriched'] ?? 0).toLocaleString('fr-FR')}
                </p>
                <p className="text-xs text-gray-500">Enrichis par IA</p>
              </div>
            </div>

            {Object.entries(stats.par_statut).length > 0 && (
              <div className="sm:col-span-3 bg-white border border-gray-200 rounded-lg p-4">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Répartition par statut</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(stats.par_statut).map(([statut, nb]) => {
                    const s = STATUT_LABELS[statut] ?? { label: statut, color: 'text-gray-600 bg-gray-50' }
                    return (
                      <span key={statut} className={`text-xs px-2.5 py-1.5 rounded-lg font-medium ${s.color}`}>
                        {s.label} : {nb}
                      </span>
                    )
                  })}
                </div>
              </div>
            )}

            {stats.categories.length > 0 && (
              <div className="sm:col-span-3 bg-white border border-gray-200 rounded-lg p-4">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Catégories principales</p>
                <div className="space-y-1.5">
                  {stats.categories.slice(0, 6).map(c => {
                    const pct = stats.total_documents > 0
                      ? Math.round((c.nb_documents / stats.total_documents) * 100)
                      : 0
                    return (
                      <div key={c.categorie} className="flex items-center gap-2">
                        <span className="text-xs text-gray-600 w-32 shrink-0 truncate">{c.categorie}</span>
                        <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                          <div className="h-full bg-blue-400 rounded-full" style={{ width: `${pct}%` }} />
                        </div>
                        <span className="text-xs text-gray-400 w-8 text-right shrink-0">{c.nb_documents}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
       </div>
      </CollapsibleSection>

      <CollapsibleSection {...secProps('set-maintenance')} id="set-maintenance" icon={<AlertTriangle size={16} className="text-amber-600" />} title="Maintenance">
       <div className="pt-1">

      {/* ── Maintenance ──────────────────────────────────── */}
      <section>
        <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
          <div className="flex items-center justify-between px-4 py-3 gap-4">
            <div>
              <p className="text-sm font-medium text-gray-700">Relancer l'IA sur les documents non analysés</p>
              <p className="text-xs text-gray-400 mt-0.5">
                Ré-analyse (résumé, catégorie, tags) tous les documents <strong>extraits mais non
                enrichis</strong> — une tâche durable par document, suivie dans « Tâches ».
              </p>
            </div>
            <button
              type="button"
              onClick={reenrichLot}
              disabled={reenrichingLot || nonAnalyses === 0}
              className="flex items-center gap-1.5 shrink-0 px-3 py-2 text-sm border border-violet-200 text-violet-600 rounded-lg hover:bg-violet-50 disabled:opacity-40 transition-colors"
            >
              {reenrichingLot ? <LoadingSpinner size={14} /> : <Bot size={14} />}
              {reenrichingLot ? 'Envoi…' : `Relancer l'IA${nonAnalyses ? ` (${nonAnalyses})` : ''}`}
            </button>
          </div>
          <div className="flex items-center justify-between px-4 py-3 gap-4">
            <div>
              <p className="text-sm font-medium text-gray-700">Ré-analyser les documents sans texte</p>
              <p className="text-xs text-gray-400 mt-0.5">
                Ré-extrait le <strong>contenu</strong> des documents extraits <strong>au texte vide</strong>
                (souvent des PDF scannés) : récupère le fichier (fetch NAS si distant, <strong>temporaire</strong>),
                relance Tika + IA — <strong>sans créer de doublon</strong>. Tâche durable.
              </p>
            </div>
            <button
              type="button"
              onClick={analyserLot}
              disabled={analysingLot || sansTexte === 0}
              className="flex items-center gap-1.5 shrink-0 px-3 py-2 text-sm border border-blue-200 text-blue-600 rounded-lg hover:bg-blue-50 disabled:opacity-40 transition-colors"
            >
              {analysingLot ? <LoadingSpinner size={14} /> : <RefreshCw size={14} />}
              {analysingLot ? 'Envoi…' : `Ré-analyser${sansTexte ? ` (${sansTexte})` : ''}`}
            </button>
          </div>
          <div className="flex items-center justify-between px-4 py-3 gap-4">
            <div>
              <p className="text-sm font-medium text-gray-700">Purger les doublons</p>
              <p className="text-xs text-gray-400 mt-0.5">
                Supprime les documents indexés plusieurs fois (même contenu ou même chemin).
                Conserve la version la mieux enrichie.
              </p>
            </div>
            <button
              type="button"
              onClick={purgerDoublons}
              disabled={purgingDoublons}
              className="flex items-center gap-1.5 shrink-0 px-3 py-2 text-sm border border-red-200 text-red-600 rounded-lg hover:bg-red-50 disabled:opacity-40 transition-colors"
            >
              {purgingDoublons ? <LoadingSpinner size={14} /> : <Trash2 size={14} />}
              {purgingDoublons ? 'Purge…' : 'Purger'}
            </button>
          </div>
        </div>
      </section>
       </div>
      </CollapsibleSection>

      <CollapsibleSection {...secProps('set-services')} id="set-services" icon={<HardDrive size={16} className="text-gray-600" />} title="Services & modèles IA">
       <div className="pt-1">

      {/* ── Services & modèles IA (configurable) ───────────── */}
      <section>
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">

          {/* URLs des services — éditables + test connexion */}
          {([
            { key: 'tika_url' as const, svc: 'tika' as const, label: 'Tika', ok: statuts.tika },
            { key: 'ollama_url' as const, svc: 'ollama' as const, label: 'Ollama', ok: statuts.ollama },
            { key: 'n8n_url' as const, svc: 'n8n' as const, label: 'n8n', ok: statuts.n8n },
          ]).map(({ key, svc, label, ok }) => (
            <div key={key} className="flex items-center gap-2">
              {ok === null ? <LoadingSpinner size={16} />
                : ok ? <CheckCircle size={16} className="text-green-500 shrink-0" />
                : <XCircle size={16} className="text-red-500 shrink-0" />}
              <label className="text-sm w-16 shrink-0 text-gray-600">{label}</label>
              <input
                type="text"
                value={config[key] ?? ''}
                onChange={e => setConfig(c => ({ ...c, [key]: e.target.value }))}
                placeholder={`URL ${label}`}
                className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
              <button
                type="button"
                onClick={() => testerService(svc)}
                disabled={testing === svc}
                className="text-xs px-2 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 shrink-0"
              >
                {testing === svc ? 'Test…' : 'Tester'}
              </button>
            </div>
          ))}

          {/* Antivirus (lecture seule — service interne) */}
          <div className="flex items-center gap-2">
            {statuts.clamav === null ? <LoadingSpinner size={16} />
              : statuts.clamav ? <CheckCircle size={16} className="text-green-500 shrink-0" />
              : <XCircle size={16} className="text-gray-300 shrink-0" />}
            <label className="text-sm w-16 shrink-0 text-gray-600">Antivirus</label>
            <span className="flex-1 text-sm text-gray-500">
              ClamAV — scan des fichiers à l'indexation {statuts.clamav ? '(actif)' : '(inactif)'}
            </span>
          </div>

          {/* Modèle par défaut + rafraîchir la liste */}
          <div className="flex items-center gap-2 pt-1 border-t border-gray-100">
            <label className="text-sm w-16 shrink-0 text-gray-600">Modèle</label>
            <select
              value={config.default_model ?? ''}
              onChange={e => setConfig(c => ({ ...c, default_model: e.target.value }))}
              title="Modèle IA par défaut"
              className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
              {config.default_model && !models.some(m => m.name === config.default_model) && (
                <option value={config.default_model}>{config.default_model}</option>
              )}
              {models.map(m => (
                <option key={m.name} value={m.name}>
                  {m.name}{m.classe === 'uncensored' ? ' 😈' : ''} ({(m.size / 1e9).toFixed(1)} GB)
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => chargerModeles()}
              disabled={loadingModels}
              title="Rafraîchir les modèles IA installés"
              className="flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 shrink-0"
            >
              <RefreshCw size={13} className={loadingModels ? 'animate-spin' : ''} />
              {models.length > 0 ? `${models.length} modèles` : 'Rafraîchir'}
            </button>
          </div>

          {/* 💡 Modèle par usage — reco locale + choix éditable (routage dynamique côté backend) */}
          {models.length > 0 && (() => {
            const r = recommanderModeles(models)
            let map: Record<string, string> = {}
            try { map = JSON.parse(config.usage_models || '{}') } catch { map = {} }
            const setUsage = (k: string, v: string) => {
              const next = { ...map }
              if (v) next[k] = v; else delete next[k]
              setConfig(c => ({ ...c, usage_models: JSON.stringify(next) }))
            }
            const USAGES = [
              { key: 'rapport', label: 'Rapports / raisonnement', reco: r.raisonnement?.name },
              { key: 'enrichissement', label: 'Enrichissement (indexation)', reco: r.rapide?.name },
              { key: 'embeddings', label: 'Recherche sémantique (embeddings)', reco: r.embeddings?.name },
              { key: 'vision', label: 'Vision / OCR de secours', reco: r.vision?.name },
              { key: 'resume_modele', label: 'Résumé de modèle (catalogue HF)', reco: r.rapide?.name },
            ]
            return (
              <div className="border-t border-gray-100 pt-3 mt-1">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                  💡 Modèle par usage <span className="normal-case text-gray-400 font-normal">— routage dynamique (« Auto » = défaut)</span>
                </p>
                <div className="space-y-1.5">
                  {USAGES.map(u => (
                    <div key={u.key} className="flex items-center gap-2 text-xs">
                      <span className="text-gray-600 w-56 shrink-0">{u.label}</span>
                      <select value={map[u.key] ?? ''} onChange={e => setUsage(u.key, e.target.value)}
                        title="Modèle pour cet usage" aria-label={`Modèle pour ${u.label}`}
                        className="flex-1 text-xs border border-gray-200 rounded-md px-2 py-1 bg-white min-w-0">
                        <option value="">Auto (défaut)</option>
                        {models.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
                      </select>
                      {u.reco && <span className="text-gray-400 shrink-0" title="Recommandé (heuristique locale)">💡 {u.reco}</span>}
                    </div>
                  ))}
                </div>
                <p className="text-[10px] text-gray-400 mt-1.5">
                  <strong>Enregistre</strong> pour appliquer. « Auto » = modèle par défaut. Le backend route chaque tâche
                  vers le modèle choisi ici. 100% local.
                </p>
              </div>
            )
          })()}

          {/* Liste des modèles installés + mises à jour */}
          <div className="border-t border-gray-100 pt-2">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Modèles installés</span>
              <span className="text-[10px] text-gray-400 italic">liste locale · MAJ → section « Demandes Mise à jour internet »</span>
            </div>
            <ul className="divide-y divide-gray-100 max-h-64 overflow-auto">
              {models.map(m => {
                const pull = pulls[m.name]
                return (
                  <li key={m.name} className="flex items-center gap-2 py-1.5 text-sm">
                    <span className="flex-1 truncate">
                      {m.name}
                      {/* Badge depuis la classe PERSISTÉE en base (renvoyée par l'API) — pas de
                          re-devinette côté client. Affinée par « Vérifier les MAJ ». */}
                      {m.classe === 'uncensored' ? (
                        <span title="Hors registre / import perso — potentiellement sans censure"
                          className="ml-1.5 align-middle"> 😈</span>
                      ) : (
                        <span title="Modèle standard / officiel (registre Ollama)"
                          className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-blue-50 text-blue-600 align-middle">officiel</span>
                      )}
                    </span>
                    <span className="text-xs text-gray-400 shrink-0">{(m.size / 1e9).toFixed(1)} GB</span>
                    {/* État MAJ */}
                    {m.update === true && (
                      <span className="flex items-center gap-1 text-xs text-amber-600 shrink-0" title="Mise à jour disponible">
                        <AlertTriangle size={13} /> MAJ
                      </span>
                    )}
                    {m.update === false && <CheckCircle size={14} className="text-green-500 shrink-0" />}
                    {/* Progression d'un téléchargement lancé depuis « Demandes Mise à jour internet ». */}
                    {pull && (
                      <span className="text-xs text-blue-600 shrink-0 w-28 text-right truncate" title={pull.status}>
                        {pull.status}{pull.pct ? ` ${pull.pct}%` : ''}
                      </span>
                    )}
                  </li>
                )
              })}
              {models.length === 0 && <li className="py-2 text-xs text-gray-400">Aucun modèle (Ollama injoignable ?)</li>}
            </ul>
          </div>

          {/* Enregistrer */}
          <div className="flex justify-end pt-1">
            <button
              type="button"
              onClick={sauvegarderConfig}
              disabled={savingConfig}
              className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              <Save size={15} /> {savingConfig ? 'Enregistrement…' : 'Enregistrer'}
            </button>
          </div>
        </div>
      </section>
       </div>
      </CollapsibleSection>

      <CollapsibleSection {...secProps('set-internet')} id="set-internet" icon={<Globe size={16} className="text-blue-600" />} title="Demandes Mise à jour internet">
       <div className="pt-1">

      {/* ── Actions réseau centralisées (100% local ailleurs) ── */}
      <section>
        <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-xs text-blue-800 mb-3">
          <strong>Matothèque est 100% local.</strong> Voici les <strong>seules</strong> actions qui
          contactent Internet — chacune sur <strong>confirmation</strong>, n'envoyant que le
          <strong> strict nécessaire</strong> (jamais un document, un tag, un résumé, un chemin ou un nom de fichier).
        </div>
        <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">

          {/* Vérifier les MAJ des modèles */}
          <div className="flex items-center justify-between px-4 py-3 gap-4">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <p className="text-sm font-medium text-gray-700">Vérifier les mises à jour des modèles IA</p>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${derniereVerif ? 'bg-green-50 text-green-600' : 'bg-gray-100 text-gray-400'}`}
                  title={derniereVerif ? 'Date de la dernière vérification (locale)' : 'Aucune vérification effectuée'}>
                  {derniereVerif
                    ? `Vérifié le ${new Date(derniereVerif).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}`
                    : 'Jamais vérifié'}
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5">
                Compare tes modèles au registre Ollama. <strong>Envoie uniquement le nom</strong> des
                modèles → <code>registry.ollama.ai</code>.
              </p>
            </div>
            <button type="button" disabled={verifMaj}
              onClick={() => setNetConfirm({
                titre: 'Vérifier les mises à jour',
                message: 'Contacte registry.ollama.ai pour comparer les versions. Seuls les NOMS des modèles sont envoyés — aucun document, tag, résumé ni nom de fichier.',
                action: () => chargerModeles(true),
              })}
              className="flex items-center gap-1.5 shrink-0 px-3 py-2 text-sm border border-blue-200 text-blue-600 rounded-lg hover:bg-blue-50 disabled:opacity-40 transition-colors">
              <RefreshCw size={14} className={verifMaj ? 'animate-spin' : ''} />
              {verifMaj ? 'Vérification…' : 'Vérifier'}
            </button>
          </div>

          {/* Modèles à mettre à jour (après vérif) */}
          <div className="px-4 py-3">
            <p className="text-sm font-medium text-gray-700 mb-0.5">Mettre à jour un modèle</p>
            {models.some(m => m.update === true) ? (
              <ul className="space-y-1.5 mt-2">
                {models.filter(m => m.update === true).map(m => {
                  const pull = pulls[m.name]
                  return (
                    <li key={m.name} className="flex items-center gap-2 text-sm">
                      <span className="flex-1 truncate">{m.name}</span>
                      {pull ? (
                        <span className="text-xs text-blue-600 shrink-0">{pull.status}{pull.pct ? ` ${pull.pct}%` : ''}</span>
                      ) : (
                        <button type="button"
                          onClick={() => setNetConfirm({
                            titre: 'Mettre à jour le modèle',
                            message: `Télécharge « ${m.name} » depuis Internet (ollama.com / Hugging Face). Téléchargement entrant — aucun document envoyé.`,
                            action: () => mettreAJourModele(m.name),
                          })}
                          className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-amber-300 text-amber-600 hover:bg-amber-50 shrink-0">
                          <Download size={13} /> Mettre à jour
                        </button>
                      )}
                    </li>
                  )
                })}
              </ul>
            ) : (
              <p className="text-xs text-gray-400 mt-0.5">
                Lance d'abord « Vérifier » ci-dessus — les modèles avec une MAJ disponible apparaîtront ici.
              </p>
            )}
          </div>

          {/* ClamAV info (auto, hors UI) */}
          <div className="px-4 py-3">
            <p className="text-sm font-medium text-gray-700">Antivirus (ClamAV) — base virale</p>
            <p className="text-xs text-gray-400 mt-0.5">
              Se met à jour <strong>automatiquement</strong> dans son conteneur (définitions antivirus,
              entrant). Aucune action manuelle, aucun document envoyé.
            </p>
          </div>
        </div>
      </section>
       </div>
      </CollapsibleSection>

      <CollapsibleSection {...secProps('set-wiki')} id="set-wiki" icon={<BookOpen size={16} className="text-purple-600" />} title="Wiki BookStack">
       <div className="pt-1">

      {/* ── Wiki BookStack (publication de tutos) ──────────── */}
      <section>
        <p className="text-xs text-gray-400 mb-3">
          Publier des documents ou rapports comme pages (tutos) sur le wiki. Le jeton est chiffré en base.
          Créez-le dans BookStack : <em>Profil → Jetons d'API</em> (avec une date d'expiration future).
        </p>
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
          {/* URL + statut + test */}
          <div className="flex items-center gap-2">
            {statuts.bookstack === null ? <LoadingSpinner size={16} />
              : statuts.bookstack ? <CheckCircle size={16} className="text-green-500 shrink-0" />
              : <XCircle size={16} className="text-gray-300 shrink-0" />}
            <label className="text-sm w-20 shrink-0 text-gray-600">URL</label>
            <input
              type="text"
              value={config.bookstack_url ?? ''}
              onChange={e => setConfig(c => ({ ...c, bookstack_url: e.target.value }))}
              placeholder="https://wiki.agesti.fr"
              className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-purple-400"
            />
            <button
              type="button"
              onClick={() => testerService('bookstack')}
              disabled={testing === 'bookstack'}
              className="text-xs px-2 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 shrink-0"
            >
              {testing === 'bookstack' ? 'Test…' : 'Tester'}
            </button>
          </div>

          {/* Token ID */}
          <div className="flex items-center gap-2">
            <span className="w-4 shrink-0" />
            <label className="text-sm w-20 shrink-0 text-gray-600">Token ID</label>
            <input
              type="text"
              value={config.bookstack_token_id ?? ''}
              onChange={e => setConfig(c => ({ ...c, bookstack_token_id: e.target.value }))}
              placeholder="Identifiant du jeton"
              className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-purple-400"
            />
          </div>

          {/* Token Secret */}
          <div className="flex items-center gap-2">
            <span className="w-4 shrink-0" />
            <label className="text-sm w-20 shrink-0 text-gray-600">Secret</label>
            <input
              type="password"
              value={config.bookstack_token_secret ?? ''}
              onChange={e => setConfig(c => ({ ...c, bookstack_token_secret: e.target.value }))}
              placeholder="••• laisser vide pour conserver le secret existant •••"
              className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-purple-400"
            />
          </div>

          <div className="flex justify-end pt-1">
            <button
              type="button"
              onClick={sauvegarderConfig}
              disabled={savingConfig}
              className="flex items-center gap-2 px-3 py-2 bg-purple-600 text-white text-sm rounded-lg hover:bg-purple-700 disabled:opacity-50"
            >
              <Save size={15} /> {savingConfig ? 'Enregistrement…' : 'Enregistrer'}
            </button>
          </div>
        </div>
      </section>
       </div>
      </CollapsibleSection>

      <CollapsibleSection {...secProps('set-hf')} id="set-hf" icon={<Bot size={16} className="text-yellow-500" />} title="HuggingFace 🤗">
       <div className="pt-1">
      {/* ── Identifiants HuggingFace (chiffrés, stockage local) ── */}
      <section>
        <p className="text-xs text-gray-400 mb-3">
          Identifiants HuggingFace (stockés <strong>chiffrés en local</strong>) pour de futurs usages :
          récupération de modèles gated/privés, recherche HF. <strong>Aucune requête réseau ici</strong> —
          toute connexion HF passera par « Demandes Mise à jour internet » avec confirmation.
        </p>
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
          {/* Token API (recommandé) */}
          <div className="flex items-center gap-2">
            <label className="text-sm w-24 shrink-0 text-gray-600">Token API</label>
            <input
              type="password"
              value={config.huggingface_token ?? ''}
              onChange={e => setConfig(c => ({ ...c, huggingface_token: e.target.value }))}
              placeholder="hf_… (recommandé) — vide = conserver l'existant"
              className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-yellow-400"
            />
          </div>
          {/* Identifiant (optionnel, legacy) */}
          <div className="flex items-center gap-2">
            <label className="text-sm w-24 shrink-0 text-gray-600">Identifiant</label>
            <input
              type="text"
              value={config.huggingface_user ?? ''}
              onChange={e => setConfig(c => ({ ...c, huggingface_user: e.target.value }))}
              placeholder="Nom d'utilisateur HF (optionnel)"
              className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-yellow-400"
            />
          </div>
          {/* Mot de passe (optionnel, legacy) */}
          <div className="flex items-center gap-2">
            <label className="text-sm w-24 shrink-0 text-gray-600">Mot de passe</label>
            <input
              type="password"
              value={config.huggingface_password ?? ''}
              onChange={e => setConfig(c => ({ ...c, huggingface_password: e.target.value }))}
              placeholder="••• optionnel — vide = conserver l'existant •••"
              className="flex-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-yellow-400"
            />
          </div>
          <div className="flex justify-between items-center pt-1">
            <button
              type="button"
              disabled={testing === 'huggingface'}
              onClick={() => setNetConfirm({
                titre: 'Tester la connexion HuggingFace',
                message: 'Contacte huggingface.co (endpoint whoami) pour vérifier le token. Seul le TOKEN est envoyé — aucun document, aucune donnée personnelle.',
                action: testerHF,
              })}
              title="Vérifie le token (appel réseau HuggingFace, sur confirmation)"
              className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg border border-yellow-300 text-yellow-700 hover:bg-yellow-50 disabled:opacity-50"
            >
              <Globe size={14} /> {testing === 'huggingface' ? 'Test…' : 'Tester 🌐'}
            </button>
            <button
              type="button"
              onClick={sauvegarderConfig}
              disabled={savingConfig}
              className="flex items-center gap-2 px-3 py-2 bg-yellow-500 text-white text-sm rounded-lg hover:bg-yellow-600 disabled:opacity-50"
            >
              <Save size={15} /> {savingConfig ? 'Enregistrement…' : 'Enregistrer'}
            </button>
          </div>
        </div>
      </section>
       </div>
      </CollapsibleSection>

      <CollapsibleSection {...secProps('set-admin')} id="set-admin" icon={<Landmark size={16} className="text-blue-600" />} title="Administration — liens">
       <div className="pt-1">
      <section>
        <p className="text-xs text-gray-400 mb-3">
          Liens affichés dans la page <strong>Administration</strong> (regroupés par section, pliable).
          Ajoute/retire des liens puis <strong>Enregistrer</strong>.
        </p>
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
          {(() => {
            let liens: { section: string; label: string; url: string }[] = []
            try { liens = JSON.parse(config.admin_links || '[]') } catch { liens = [] }
            const majLiens = (arr: typeof liens) => setConfig(c => ({ ...c, admin_links: JSON.stringify(arr) }))
            const ajouter = () => {
              if (!nouveauLien.label.trim() || !nouveauLien.url.trim()) return
              const url = /^https?:\/\//.test(nouveauLien.url) ? nouveauLien.url : `https://${nouveauLien.url}`
              majLiens([...liens, { section: nouveauLien.section.trim() || 'Divers', label: nouveauLien.label.trim(), url }])
              setNouveauLien({ section: nouveauLien.section, label: '', url: '' })
            }
            const supprimer = (i: number) => majLiens(liens.filter((_, idx) => idx !== i))
            return (
              <>
                {liens.length === 0 ? (
                  <p className="text-xs text-gray-400">Aucun lien.</p>
                ) : (
                  <ul className="divide-y divide-gray-100">
                    {liens.map((l, i) => (
                      <li key={i} className="flex items-center gap-2 py-1.5 text-sm">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 shrink-0">{l.section}</span>
                        <span className="font-medium text-gray-700 truncate">{l.label}</span>
                        <span className="text-xs text-gray-400 truncate flex-1">{l.url}</span>
                        <button type="button" onClick={() => supprimer(i)} title="Retirer" className="text-gray-300 hover:text-red-500 shrink-0"><Trash2 size={13} /></button>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="flex gap-2 flex-wrap pt-2 border-t border-gray-100">
                  <input value={nouveauLien.section} onChange={e => setNouveauLien(v => ({ ...v, section: e.target.value }))}
                    placeholder="Section (ex. Médical)" list="admin-sections" aria-label="Section"
                    className="text-xs border border-gray-200 rounded-md px-2 py-1.5 w-36" />
                  <datalist id="admin-sections">{[...new Set(liens.map(l => l.section))].map(s => <option key={s} value={s} />)}</datalist>
                  <input value={nouveauLien.label} onChange={e => setNouveauLien(v => ({ ...v, label: e.target.value }))}
                    placeholder="Libellé (ex. Doctolib)" aria-label="Libellé"
                    className="text-xs border border-gray-200 rounded-md px-2 py-1.5 flex-1 min-w-[8rem]" />
                  <input value={nouveauLien.url} onChange={e => setNouveauLien(v => ({ ...v, url: e.target.value }))}
                    placeholder="https://…" aria-label="URL"
                    className="text-xs border border-gray-200 rounded-md px-2 py-1.5 flex-1 min-w-[10rem] font-mono" />
                  <button type="button" onClick={ajouter}
                    className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 flex items-center gap-1"><Plus size={13} /> Ajouter</button>
                </div>
                <div className="flex justify-end">
                  <button type="button" onClick={sauvegarderConfig} disabled={savingConfig}
                    className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50">
                    <Save size={15} /> {savingConfig ? 'Enregistrement…' : 'Enregistrer'}
                  </button>
                </div>
              </>
            )
          })()}
        </div>
      </section>
       </div>
      </CollapsibleSection>

      <CollapsibleSection {...secProps('set-logs')} id="set-logs" icon={<FileText size={16} className="text-gray-600" />} title="Logs & historique">
       <div className="pt-1">
      <section>
        <p className="text-xs text-gray-400 mb-3">
          Historique des tâches (<strong>qui fait quoi</strong> / <strong>que s'est-il passé</strong>)
          + journal technique (<strong>debug</strong>), et <strong>purge</strong> de l'historique
          (fenêtre de confirmation, jamais les tâches en cours).
        </p>
        <Link to="/logs" className="inline-flex items-center gap-2 px-3 py-2 bg-gray-800 text-white text-sm rounded-lg hover:bg-gray-900">
          <FileText size={15} /> Ouvrir les logs
        </Link>
      </section>
       </div>
      </CollapsibleSection>

      <CollapsibleSection {...secProps('set-apropos')} id="set-apropos" icon={<FileText size={16} className="text-gray-500" />} title="À propos">
       <div className="pt-1">

      {/* ── À propos ──────────────────────────────────────── */}
      <section>
        <div className="bg-white border border-gray-200 rounded-lg p-4 text-sm text-gray-600 space-y-1">
          <p><strong>Matothèque</strong> — Plateforme locale de gestion documentaire intelligente (version affichée dans la barre latérale)</p>
          <p className="text-gray-400">100% local · Aucune donnée envoyée vers le cloud</p>
          <div className="flex flex-wrap gap-2 pt-2">
            {['Ollama', 'Apache Tika', 'PostgreSQL + pgvector', 'FastAPI', 'React 18'].map(tech => (
              <span key={tech} className="text-xs px-2 py-0.5 bg-gray-100 text-gray-500 rounded-full">{tech}</span>
            ))}
          </div>
        </div>
      </section>

       </div>
      </CollapsibleSection>

      {/* Garde-fou 100% local : confirmation avant toute action qui contacte Internet. */}
      {netConfirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => setNetConfirm(null)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2">🌐 {netConfirm.titre}</h2>
            <p className="text-sm text-gray-600 mb-3">{netConfirm.message}</p>
            <p className="text-xs text-gray-400 mb-4">
              Matothèque reste <strong>100% local</strong> : c'est le seul moment où l'on sort sur
              Internet, et uniquement parce que tu l'as demandé. <strong>Aucun document</strong> n'est envoyé.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setNetConfirm(null)}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50">Annuler</button>
              <button type="button" onClick={() => { const a = netConfirm.action; setNetConfirm(null); a() }}
                className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">Continuer</button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
