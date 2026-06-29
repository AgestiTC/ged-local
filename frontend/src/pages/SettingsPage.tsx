/**
 * Page Paramètres — Configuration des dossiers surveillés, prompts, templates, stats, services
 */
import { useCallback, useEffect, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  AlertTriangle, CheckCircle, Database, Download,
  Edit2, FileText, HardDrive, MessageSquare, Plus, RefreshCw,
  Save, Trash2, Upload, X, XCircle,
} from 'lucide-react'
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

// ── Composant principal ───────────────────────────────────────────────────────

export default function SettingsPage() {
  const [dossiers, setDossiers] = useState<DossierSurveille[]>([])
  const [statuts, setStatuts] = useState<{ tika: boolean | null; ollama: boolean | null; n8n: boolean | null; clamav: boolean | null }>({ tika: null, ollama: null, n8n: null, clamav: null })
  const [config, setConfig] = useState<ConfigUpdate>({ tika_url: '', ollama_url: '', n8n_url: '', default_model: '' })
  const [savingConfig, setSavingConfig] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [models, setModels] = useState<OllamaModel[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [verifMaj, setVerifMaj] = useState(false)
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

  const toast = useToast()

  useEffect(() => {
    foldersApi.list().then(d => setDossiers(d.dossiers)).catch(() => {})
    systemApi.services().then(s => setStatuts({ tika: s.tika.ok, ollama: s.ollama.ok, n8n: s.n8n?.ok ?? false, clamav: s.clamav?.ok ?? false }))
      .catch(() => setStatuts({ tika: false, ollama: false, n8n: false, clamav: false }))
    systemApi.getConfig().then(c => setConfig({
      tika_url: c.tika_url.valeur, ollama_url: c.ollama_url.valeur,
      n8n_url: c.n8n_url.valeur, default_model: c.default_model.valeur,
    })).catch(() => {})
    chargerModeles()
    statsApi.getDocumentStats().then(setStats).catch(() => {})
    promptsApi.list().then(d => setPrompts(d.prompts ?? [])).catch(() => {})
    templatesApi.list().then(d => setTemplates(d.templates ?? [])).catch(() => {})
  }, [])

  async function chargerModeles(checkUpdates = false) {
    if (checkUpdates) setVerifMaj(true); else setLoadingModels(true)
    try {
      const r = await systemApi.models(checkUpdates)
      setModels(r.models)
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

  const testerService = async (service: 'tika' | 'ollama' | 'n8n') => {
    setTesting(service)
    try {
      const r = await systemApi.testService(service, config)   // teste les URLs saisies (avant sauvegarde)
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
      setStatuts({ tika: s.tika.ok, ollama: s.ollama.ok, n8n: s.n8n?.ok ?? false, clamav: s.clamav?.ok ?? false })
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
    <div className="max-w-3xl mx-auto p-6 flex flex-col gap-3">

      <CollapsibleSection id="set-sources" defaultOpen icon={<Database size={16} className="text-blue-600" />} title="Sources & indexation">
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

      <CollapsibleSection id="set-generation" defaultOpen={false} icon={<MessageSquare size={16} className="text-amber-600" />} title="Génération — prompts & templates">
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

      <CollapsibleSection id="set-systeme" defaultOpen={false} icon={<HardDrive size={16} className="text-gray-600" />} title="Système & IA — stats, maintenance, services, à propos">
       <div className="flex flex-col gap-6 pt-1">

      {/* ── Statistiques ─────────────────────────────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-3">Statistiques</h2>
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

      {/* ── Maintenance ──────────────────────────────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-3">Maintenance</h2>
        <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
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

      {/* ── Services & modèles IA (configurable) ───────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-3">Services &amp; modèles IA</h2>
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
                <option key={m.name} value={m.name}>{m.name} ({(m.size / 1e9).toFixed(1)} GB)</option>
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

          {/* Liste des modèles installés + mises à jour */}
          <div className="border-t border-gray-100 pt-2">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Modèles installés</span>
              <button
                type="button"
                onClick={() => chargerModeles(true)}
                disabled={verifMaj}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
              >
                <RefreshCw size={12} className={verifMaj ? 'animate-spin' : ''} />
                {verifMaj ? 'Vérification…' : 'Vérifier les MAJ'}
              </button>
            </div>
            <ul className="divide-y divide-gray-100 max-h-64 overflow-auto">
              {models.map(m => {
                const pull = pulls[m.name]
                return (
                  <li key={m.name} className="flex items-center gap-2 py-1.5 text-sm">
                    <span className="flex-1 truncate">{m.name}</span>
                    <span className="text-xs text-gray-400 shrink-0">{(m.size / 1e9).toFixed(1)} GB</span>
                    {/* État MAJ */}
                    {m.update === true && (
                      <span className="flex items-center gap-1 text-xs text-amber-600 shrink-0" title="Mise à jour disponible">
                        <AlertTriangle size={13} /> MAJ
                      </span>
                    )}
                    {m.update === false && <CheckCircle size={14} className="text-green-500 shrink-0" />}
                    {m.update === null && <span className="text-xs text-gray-300 shrink-0" title="Modèle hors registre (custom)">?</span>}
                    {/* Action MAJ / progression */}
                    {pull ? (
                      <span className="text-xs text-blue-600 shrink-0 w-28 text-right truncate" title={pull.status}>
                        {pull.status}{pull.pct ? ` ${pull.pct}%` : ''}
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => mettreAJourModele(m.name)}
                        title={m.update === true ? 'Mettre à jour ce modèle' : 'Re-télécharger / mettre à jour'}
                        className={`p-1 rounded-md border shrink-0 ${m.update === true
                          ? 'border-amber-300 text-amber-600 hover:bg-amber-50'
                          : 'border-gray-200 text-gray-400 hover:bg-gray-50'}`}
                      >
                        <Download size={13} />
                      </button>
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

      {/* ── À propos ──────────────────────────────────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-3">À propos</h2>
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

    </div>
  )
}
