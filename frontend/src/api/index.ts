/**
 * Couche API — DocFlow AI
 * ========================
 * Fonctions typées pour chaque endpoint backend.
 */

import { apiClient, apiClientLong } from './client'
import type {
  Document,
  DocumentVersion,
  DossierSurveille,
  GenerateReportRequest,
  Job,
  MetadonneeIA,
  PromptPreset,
  Template,
} from '../types'

// ─── Documents ───────────────────────────────────────────────────────────────

export interface ListDocumentsParams {
  page?: number
  page_size?: number
  statut?: string
  extension?: string
  source?: string
  q?: string
  tag?: string
  categorie?: string  // '__sans__' = non classé
  texte?: boolean     // true = uniquement docs avec texte (exclut médias catalogués)
}

export type GroupBy = 'extension' | 'categorie' | 'tag'
export interface DocumentGroup { valeur: string | null; nb: number }

export interface ListDocumentsResponse {
  total: number
  page: number
  page_size: number
  pages: number
  documents: Document[]
}

export const documentsApi = {
  list: (params?: ListDocumentsParams) =>
    apiClient.get<ListDocumentsResponse>('/documents', { params }).then(r => r.data),

  get: (id: string) =>
    apiClient.get<Document>(`/documents/${id}`).then(r => r.data),

  getText: (id: string) =>
    apiClient.get<{ document_id: string; nom: string; texte: string; nb_caracteres: number }>(
      `/documents/${id}/text`
    ).then(r => r.data),

  /** URL (relative → proxy) du fichier original : aperçu inline ou téléchargement. */
  fileUrl: (id: string, download = false) => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/documents/${id}/file${download ? '?download=true' : ''}`
  },

  groups: (by: GroupBy) =>
    apiClient.get<{ by: GroupBy; nb_groupes: number; groupes: DocumentGroup[] }>(
      '/documents/groups', { params: { by } }
    ).then(r => r.data),

  // Relance l'enrichissement IA (tâche durable) → renvoie un job_id à suivre via jobsApi
  enrich: (id: string) =>
    apiClient.post<{ job_id: string; statut: string; deja?: boolean }>(`/documents/${id}/enrich`).then(r => r.data),

  getMetadata: (id: string) =>
    apiClient.get<MetadonneeIA>(`/documents/${id}/metadata`).then(r => r.data),

  patchMetadata: (id: string, data: Partial<Pick<MetadonneeIA, 'tags' | 'categorie' | 'sous_categorie' | 'resume' | 'niveau_confidentialite' | 'mots_cles'>>) =>
    apiClient.patch<MetadonneeIA>(`/documents/${id}/metadata`, data).then(r => r.data),

  getVersions: (id: string) =>
    apiClient.get<{ document_id: string; versions: DocumentVersion[] }>(`/documents/${id}/versions`).then(r => r.data),

  delete: (id: string) =>
    apiClient.delete(`/documents/${id}`).then(r => r.data),

  purgeDoublons: () =>
    apiClient.post<{ supprimes: number; message: string }>('/documents/purge-duplicates').then(r => r.data),

  // Relance l'IA en lot sur les documents extraits mais non enrichis (tâches durables).
  reenrichBatch: () =>
    apiClient.post<{ enqueued: number; message: string }>('/documents/reenrich-batch').then(r => r.data),

  // Analyse le CONTENU d'un doc (média/doc au texte vide), local ou SMB (fetch temporaire, zéro doublon).
  analyze: (id: string) =>
    apiClient.post<{ job_id: string; statut: string; deja?: boolean }>(`/documents/${id}/analyze`).then(r => r.data),

  // Analyse de contenu en lot : scope = empty (docs sans texte) | media (médias) | all.
  analyzeBatch: (scope: 'media' | 'empty' | 'all' = 'empty') =>
    apiClient.post<{ enqueued: number; message: string }>('/documents/analyze-batch', null, { params: { scope } }).then(r => r.data),

  // Compteurs réels pour les boutons de maintenance.
  maintenanceCounts: () =>
    apiClient.get<{ reenrich: number; sans_texte: number; medias: number }>('/documents/maintenance/counts').then(r => r.data),
}

// ─── Jobs (tâches durables) ───────────────────────────────────────────────────

export interface JobInfo {
  id: string
  type: string
  statut: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  progress_message: string | null
  document_id: string | null
  parametres: Record<string, unknown> | null
  resultat: Record<string, unknown> | null
  erreur: string | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
}

export const jobsApi = {
  list: (params?: { statut?: string; type?: string; limit?: number }) =>
    apiClient.get<{ jobs: JobInfo[] }>('/jobs', { params }).then(r => r.data),
  get: (id: string) =>
    apiClient.get<JobInfo>(`/jobs/${id}`).then(r => r.data),
  cancel: (id: string) =>
    apiClient.post<{ job_id: string; statut: string }>(`/jobs/${id}/cancel`).then(r => r.data),
  demo: (etapes = 5) =>
    apiClient.post<{ job_id: string; statut: string }>('/jobs/demo', { etapes }).then(r => r.data),
}

/**
 * Suit un job jusqu'à son état final (completed|failed|cancelled) en pollant `jobsApi.get`.
 * `onProgress` est appelé à chaque tick. Renvoie le job final.
 */
export async function suivreJob(
  jobId: string,
  onProgress?: (job: JobInfo) => void,
  intervalleMs = 1000,
): Promise<JobInfo> {
  // Attente entre deux polls (pas de dépendance externe).
  const pause = (ms: number) => new Promise<void>(r => { setTimeout(r, ms) })
  for (;;) {
    const job = await jobsApi.get(jobId)
    onProgress?.(job)
    if (job.statut === 'completed' || job.statut === 'failed' || job.statut === 'cancelled') return job
    await pause(intervalleMs)
  }
}

// ─── Doublons ────────────────────────────────────────────────────────────────

export interface DuplicateFile {
  chemin: string
  nom: string
  relatif: string
  taille_octets: number
  garder: boolean
}

export interface DuplicateGroup {
  hash: string
  taille_octets: number
  fichiers: DuplicateFile[]
}

export interface DuplicatesResponse {
  groupes: DuplicateGroup[]
  nb_groupes: number
  nb_fichiers: number
  octets_recuperables: number
  dossier_quarantaine: string
}

export interface QuarantineResponse {
  deplaces: Array<{ chemin: string; destination: string }>
  erreurs: Array<{ chemin: string; erreur: string }>
  nb_deplaces: number
  nb_erreurs: number
  index_retires: number
  dossier_quarantaine: string
}

export const duplicatesApi = {
  // Scan disque : potentiellement long → client à timeout étendu
  scan: () => apiClientLong.get<DuplicatesResponse>('/duplicates').then(r => r.data),

  quarantine: (chemins: string[]) =>
    apiClient.post<QuarantineResponse>('/duplicates/quarantine', { chemins }).then(r => r.data),
}

// ─── Upload ──────────────────────────────────────────────────────────────────

export interface UploadResponse {
  jobs: Array<{ fichier: string; job_id?: string; statut: string; raison?: string }>
}

export const uploadApi = {
  uploadFiles: (files: File[], onProgress?: (pct: number) => void, folderTag?: string) => {
    const form = new FormData()
    files.forEach(f => form.append('files', f))
    if (folderTag) form.append('folder_tag', folderTag)
    return apiClient.post<UploadResponse>('/upload', form, {
      onUploadProgress: e => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    }).then(r => r.data)
  },

  uploadZip: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<{ fichier: string; job_id: string; statut: string }>(
      '/upload/zip', form,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    ).then(r => r.data)
  },
}

// ─── Extraction ──────────────────────────────────────────────────────────────

export const extractApi = {
  getJobStatus: (jobId: string) =>
    apiClient.get<Job & { parametres?: unknown; resultat?: unknown }>(`/extract/status/${jobId}`).then(r => r.data),

  relancer: (documentId: string) =>
    apiClient.post<{ document_id: string; job_id: string; statut: string }>(`/extract/${documentId}`).then(r => r.data),

  listJobs: (params?: { statut?: string; type?: string; limit?: number }) =>
    apiClient.get<{ total: number; jobs: Job[] }>('/extract/jobs', { params }).then(r => r.data),
}

// ─── Génération ──────────────────────────────────────────────────────────────

export interface GenerateResponse {
  job_id: string
  statut: string
  nb_documents: number
  model: string
  stream_url: string
}

export const generateApi = {
  startReport: (request: GenerateReportRequest) =>
    apiClientLong.post<GenerateResponse>('/generate/report', request).then(r => r.data),

  getStatus: (jobId: string) =>
    apiClient.get<{ job_id: string; statut: string; nb_chars_generes: number; erreur?: string }>(
      `/generate/status/${jobId}`
    ).then(r => r.data),

  /** Retourne l'URL SSE pour EventSource (relative si VITE_API_URL vide → proxy nginx) */
  getStreamUrl: (jobId: string) => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/generate/stream/${jobId}`
  },
}

// ─── Export ──────────────────────────────────────────────────────────────────

export const exportApi = {
  toPdf: async (content: string, title: string): Promise<void> => {
    const response = await apiClientLong.post(
      '/export/pdf',
      { content, title },
      { responseType: 'blob' }
    )
    const url = URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${title.replace(/\s+/g, '_')}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  },

  toDocx: async (content: string, title: string): Promise<void> => {
    const response = await apiClientLong.post(
      '/export/docx',
      { content, title },
      { responseType: 'blob' }
    )
    const url = URL.createObjectURL(
      new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      })
    )
    const a = document.createElement('a')
    a.href = url
    a.download = `${title.replace(/\s+/g, '_')}.docx`
    a.click()
    URL.revokeObjectURL(url)
  },
}

// ─── Recherche ───────────────────────────────────────────────────────────────

export interface SearchResponse {
  query: string
  type: string
  total: number
  offset: number
  limit: number
  has_more: boolean
  resultats: Array<{
    id: string
    nom: string
    extension: string
    taille_octets?: number
    statut: string
    chemin_copie?: string
    score: number
    date_import: string
    metadonnees_ia: {
      categorie?: string
      tags: string[]
      resume?: string
      langue?: string
    }
  }>
}

export const searchApi = {
  search: (params: { q: string; type?: string; limit?: number; offset?: number; categorie?: string; extension?: string }) =>
    apiClient.get<SearchResponse>('/search', { params }).then(r => r.data),

  getTags: () =>
    apiClient.get<{ total: number; tags: Array<{ tag: string; nb_documents: number }> }>('/search/tags').then(r => r.data),

  getCategories: () =>
    apiClient.get<{ total: number; categories: Array<{ categorie: string; nb_documents: number }> }>(
      '/search/categories'
    ).then(r => r.data),
}

// ─── Dossiers ────────────────────────────────────────────────────────────────

export interface BrowseResponse {
  chemin_actuel: string
  chemin_parent: string | null
  dossiers: Array<{ nom: string; chemin: string; type: 'dossier' }>
  fichiers: Array<{ nom: string; chemin: string; type: 'fichier'; extension: string; taille_octets: number }>
}

export const foldersApi = {
  list: () =>
    apiClient.get<{ dossiers: DossierSurveille[] }>('/folders').then(r => r.data),

  add: (data: { chemin: string; nom_affichage?: string; recursive?: boolean; extensions_filtrees?: string[]; intervalle_scan_secondes?: number }) =>
    apiClient.post<DossierSurveille>('/folders', data).then(r => r.data),

  update: (id: string, data: Partial<DossierSurveille>) =>
    apiClient.put<DossierSurveille>(`/folders/${id}`, data).then(r => r.data),

  remove: (id: string, supprimerDocuments = false) =>
    apiClient.delete(`/folders/${id}`, { params: { supprimer_documents: supprimerDocuments } }).then(r => r.data),

  scan: (id: string) =>
    apiClient.post(`/folders/${id}/scan`).then(r => r.data),

  browse: (path: string) =>
    apiClient.get<BrowseResponse>('/folders/browse', { params: { path } }).then(r => r.data),
}

// ─── Templates ───────────────────────────────────────────────────────────────

export const templatesApi = {
  list: () =>
    apiClient.get<{ templates: Template[] }>('/templates').then(r => r.data),

  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<Template>('/templates', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },

  get: (id: string) =>
    apiClient.get<Template>(`/templates/${id}`).then(r => r.data),

  delete: (id: string) =>
    apiClient.delete(`/templates/${id}`).then(r => r.data),
}

// ─── Prompts ─────────────────────────────────────────────────────────────────

export const promptsApi = {
  list: () =>
    apiClient.get<{ prompts: PromptPreset[] }>('/prompts').then(r => r.data),

  create: (data: Omit<PromptPreset, 'id' | 'created_at'>) =>
    apiClient.post<PromptPreset>('/prompts', data).then(r => r.data),

  update: (id: string, data: Partial<PromptPreset>) =>
    apiClient.put<PromptPreset>(`/prompts/${id}`, data).then(r => r.data),

  delete: (id: string) =>
    apiClient.delete(`/prompts/${id}`).then(r => r.data),
}

// ─── Comparatif ──────────────────────────────────────────────────────────────

export interface CompareResponse {
  job_id: string
  statut: string
  nb_groupes: number
  colonnes: string[]
  stream_url: string
}

export const compareApi = {
  start: (request: { groupes: { nom: string; document_ids: string[] }[]; template_id: string; model?: string; instructions?: string }) =>
    apiClientLong.post<CompareResponse>('/generate/compare', request).then(r => r.data),

  getStreamUrl: (jobId: string) => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/generate/compare/stream/${jobId}`
  },

  getDownloadUrl: (jobId: string) => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/generate/compare/download/${jobId}`
  },
}

// ─── Stats ───────────────────────────────────────────────────────────────────

export interface DocumentStats {
  total_documents: number
  par_statut: Record<string, number>
  taille_totale_octets: number
  categories: Array<{ categorie: string; nb_documents: number }>
}

export const statsApi = {
  getDocumentStats: () =>
    apiClient.get<DocumentStats>('/documents/stats').then(r => r.data),
}

// ─── Système ─────────────────────────────────────────────────────────────────

export interface ServiceStatus { url: string; ok: boolean }
export interface BookStackStatus extends ServiceStatus { configure?: boolean }
export interface ServicesStatus { tika: ServiceStatus; ollama: ServiceStatus; n8n: ServiceStatus; clamav?: ServiceStatus; bookstack?: BookStackStatus }
export interface OllamaModel {
  name: string; size: number; digest?: string
  famille?: string | null; parametres?: string | null
  update?: boolean | null   // true = MAJ dispo, false = à jour, null = inconnu
}
export interface PullProgress { status: string; completed?: number; total?: number; error?: string }
export interface ConfigEntry { valeur: string; source: 'base' | 'env'; defini?: boolean }
export interface SystemConfig {
  tika_url: ConfigEntry; ollama_url: ConfigEntry; n8n_url: ConfigEntry; default_model: ConfigEntry
  bookstack_url?: ConfigEntry; bookstack_token_id?: ConfigEntry; bookstack_token_secret?: ConfigEntry
  huggingface_token?: ConfigEntry; huggingface_user?: ConfigEntry; huggingface_password?: ConfigEntry
}
export interface ConfigUpdate {
  tika_url?: string; ollama_url?: string; n8n_url?: string; default_model?: string
  bookstack_url?: string; bookstack_token_id?: string; bookstack_token_secret?: string
  huggingface_token?: string; huggingface_user?: string; huggingface_password?: string
}

// ─── Sources (local / SMB) ────────────────────────────────────────────────────

export interface Source {
  id: string; libelle: string; type: 'local' | 'smb'
  chemin_base?: string | null; hote?: string | null; domaine?: string | null
  identifiant?: string | null; secret_defini: boolean; actif: boolean
}
export interface SourceInput {
  libelle: string; type: 'local' | 'smb'
  chemin_base?: string; hote?: string; domaine?: string; identifiant?: string; secret?: string
}
export interface BrowseEntry { nom: string; dossier: boolean; taille: number }

export interface IndexedNode { chemin: string; nom: string; nb: number; enfants: IndexedNode[] }
export interface IndexedTree { racine: string; nb_documents: number; arbre: IndexedNode[] }

export const sourcesApi = {
  list: () => apiClient.get<{ sources: Source[] }>('/sources').then(r => r.data.sources),
  create: (s: SourceInput) => apiClient.post<Source>('/sources', s).then(r => r.data),
  update: (id: string, s: SourceInput) => apiClient.put<Source>(`/sources/${id}`, s).then(r => r.data),
  remove: (id: string) => apiClient.delete(`/sources/${id}`).then(r => r.data),
  test: (s: SourceInput) => apiClient.post<{ ok: boolean; erreur?: string; partages?: string[]; chemin?: string }>('/sources/test', s).then(r => r.data),
  shares: (id: string) => apiClient.get<{ partages: string[] }>(`/sources/${id}/shares`).then(r => r.data.partages),
  browse: (id: string, chemin = '/', partage?: string) =>
    apiClient.get<{ entries: BrowseEntry[] }>(`/sources/${id}/browse`, { params: { chemin, partage } }).then(r => r.data.entries),
  index: (id: string, chemin: string, partage?: string) =>
    apiClient.post<{ message: string }>(`/sources/${id}/index`, { chemin, partage, recursive: true }).then(r => r.data),
  indexed: (id: string) =>
    apiClientLong.get<IndexedTree>(`/sources/${id}/indexed`).then(r => r.data),
  deindex: (id: string, chemins: string[]) =>
    apiClient.post<{ retires: number }>(`/sources/${id}/deindex`, { chemins }).then(r => r.data),
  progression: (id: string) =>
    apiClient.get<{ en_cours: boolean; phase: string; total: number; fait: number }>(
      `/sources/${id}/progression`
    ).then(r => r.data),
}

// ─── Assistant (constitution de dossier) ──────────────────────────────────────

export interface PieceProposee {
  libelle: string
  documents: Array<{ id: string; nom: string; extension: string; categorie?: string | null; score: number }>
}

export const assistantApi = {
  // Déduit les pièces attendues d'un besoin + propose les fichiers (LLM + recherche → lent)
  pieces: (besoin: string, model?: string) =>
    apiClientLong.post<{ besoin: string; pieces: PieceProposee[] }>(
      '/assistant/pieces', { besoin, model }
    ).then(r => r.data),
}

// ─── Présentations (diaporama IA) ─────────────────────────────────────────────

export interface Slide { titre: string; points: string[] }
export interface Presentation {
  id: string; titre: string; theme?: string | null
  slides: Slide[]; modele_utilise?: string | null; created_at?: string
}

export const presentationsApi = {
  // Génération IA = tâche durable → renvoie un job_id à suivre (jobsApi/suivreJob)
  creer: (document_ids: string[], consigne?: string, model?: string) =>
    apiClient.post<{ job_id: string; statut: string }>('/presentations', { document_ids, consigne, model }).then(r => r.data),

  get: (id: string) =>
    apiClient.get<Presentation>(`/presentations/${id}`).then(r => r.data),

  pptxUrl: (id: string) => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/presentations/${id}/pptx`
  },
}

// ─── Corbeille (déplacer vers « À supprimer » + restaurer) ────────────────────

export const corbeilleApi = {
  // Déplace le fichier vers la corbeille du NAS + retire de l'index (SMB peut être lent)
  envoyer: (documentId: string) =>
    apiClientLong.post<{ corbeille_id: string; nom: string; chemin_corbeille: string }>(
      `/corbeille/envoyer/${documentId}`
    ).then(r => r.data),

  // Annule : remet le fichier à sa place + ré-indexe
  restaurer: (corbeilleId: string) =>
    apiClientLong.post<{ nom: string; chemin_origine: string }>(
      `/corbeille/${corbeilleId}/restaurer`
    ).then(r => r.data),

  liste: () =>
    apiClient.get<{ elements: Array<{ id: string; nom: string; chemin_origine: string; chemin_corbeille: string; date: string }> }>(
      '/corbeille'
    ).then(r => r.data.elements),
}

// ─── Réorganisation d'arborescence (IA) ───────────────────────────────────────

export interface OrganizeDoc { id: string; nom: string; categorie: string; chemin_actuel: string }
export interface OrganizeFolder { dossier: string; nb: number; documents: OrganizeDoc[] }
export interface OrganizeProposal {
  criteres: string; consigne: string | null
  nb_documents: number; nb_dossiers: number; arborescence: OrganizeFolder[]
}

export const organizeApi = {
  propose: (consigne?: string, inclure_annee = true) =>
    apiClientLong.post<OrganizeProposal>('/organize/propose', { consigne, inclure_annee }).then(r => r.data),
}

// ─── BookStack (publication wiki) ─────────────────────────────────────────────

export interface BookStackBook { id: number; name: string; slug?: string }
export interface BookStackChapter { id: number; name: string; book_id?: number }
export interface BookStackTargets { books: BookStackBook[]; chapters: BookStackChapter[] }
export interface PublishResult { success: boolean; page_id: number; page_url: string; titre: string }

export interface PublishInput {
  titre: string
  markdown?: string
  document_id?: string
  book_id?: number
  chapter_id?: number
  /** Nom d'un livre à créer à la volée (idempotent côté backend) */
  new_book?: string
  /** Nom d'un chapitre à créer (rattaché à book_id ou new_book) */
  new_chapter?: string
}

export interface SuggestInput {
  markdown?: string
  document_id?: string
}

export interface BookStackSuggestion {
  titre: string
  book_id: number | null
  book_name: string | null
  nouveau_livre: string | null
  chapitre: string | null
  raison: string | null
}

export const bookstackApi = {
  // Livres + chapitres où publier (nécessite BookStack configuré)
  targets: () =>
    apiClient.get<BookStackTargets>('/bookstack/targets').then(r => r.data),

  // Crée une page (tuto) dans le wiki
  publish: (input: PublishInput) =>
    apiClientLong.post<PublishResult>('/bookstack/publish', input).then(r => r.data),

  // Propose un titre + emplacement par rapprochement thématique (LLM)
  suggest: (input: SuggestInput) =>
    apiClientLong.post<BookStackSuggestion>('/bookstack/suggest', input).then(r => r.data),
}

export const systemApi = {
  // Version applicative (source de vérité = fichier VERSION côté backend)
  version: () =>
    apiClient.get<{ name: string; version: string }>('/version').then(r => r.data),

  // Statut live des services (via backend → fiable derrière le proxy)
  services: () =>
    apiClient.get<ServicesStatus>('/system/services').then(r => r.data),

  getConfig: () =>
    apiClient.get<{ config: SystemConfig }>('/system/config').then(r => r.data.config),

  updateConfig: (data: ConfigUpdate) =>
    apiClient.put<{ config: SystemConfig; mis_a_jour: string[] }>('/system/config', data).then(r => r.data),

  testService: (service: 'tika' | 'ollama' | 'n8n' | 'bookstack' | 'huggingface', overrides?: ConfigUpdate) =>
    apiClient.post<{ service: string; url?: string; ok: boolean; configure?: boolean; user?: string; type?: string; erreur?: string }>(`/system/test/${service}`, overrides ?? {}).then(r => r.data),

  // Modèles Ollama installés (dynamique) — alimente le sélecteur + Paramètres
  models: (checkUpdates = false) =>
    apiClient.get<{ models: OllamaModel[]; defaut: string }>('/system/models', {
      params: checkUpdates ? { check_updates: true } : undefined,
    }).then(r => r.data),

  // Met à jour / télécharge un modèle (ollama pull) en streaming de progression
  pullModel: async (name: string, onProgress: (p: PullProgress) => void) => {
    const base = apiClient.defaults.baseURL ?? ''
    const resp = await fetch(`${base}/system/models/pull`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (!resp.ok || !resp.body) throw new Error(`pull ${resp.status}`)
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (line.trim()) { try { onProgress(JSON.parse(line) as PullProgress) } catch { /* ignore */ } }
      }
    }
  },
}

// ─── HuggingFace — catalogue de modèles (exploration du hub) ──────────────────
export interface HfModel {
  id: string
  categorie: string | null
  created_at: string | null
  last_modified: string | null
  maintained: boolean
  uncensored: boolean
  gated: boolean
  downloads: number
  likes: number
  gguf: boolean
  tags: string[]
}
export interface HfCatalog {
  ok: boolean
  category: string
  count: number
  models: HfModel[]
  erreur?: string
  cache?: boolean
}
export interface HfCatalogParams {
  category?: 'llm' | 'embeddings' | 'vision' | 'audio'
  max_age_years?: number
  maintained_days?: number
  maintained_only?: boolean
  sort?: 'downloads' | 'likes' | 'lastModified'
  limit?: number
}

export const huggingfaceApi = {
  // Appel réseau HF — à déclencher uniquement sur confirmation (garde-fou 100% local).
  catalog: (params: HfCatalogParams) =>
    apiClient.get<HfCatalog>('/huggingface/catalog', { params }).then(r => r.data),
}
