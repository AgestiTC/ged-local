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

/**
 * Message d'erreur LISIBLE renvoyé par l'API (`detail` de FastAPI), sinon message réseau.
 * À utiliser dans les `catch` plutôt qu'un texte générique : le backend explique souvent
 * précisément quoi faire (ex. « Mot de passe illisible : re-saisis-le »), et l'avaler
 * laisse l'utilisateur sans piste.
 */
export function extractApiError(e: unknown, defaut = 'Erreur inconnue'): string {
  if (e && typeof e === 'object') {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    if (err.response?.data?.detail) return err.response.data.detail
    if (err.message) return err.message
  }
  return defaut
}

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

export interface TreeNode { chemin: string; nom: string; nb: number }
export interface TreeFile {
  id: string; nom: string; extension: string; statut: string; taille_octets?: number; chemin: string
  /** Porte du texte extrait → utilisable comme matière d'un rapport. Faux = média/scan sans texte. */
  exploitable?: boolean
  /** Nombre de caractères extraits — base HONNÊTE de l'estimation du contexte (≠ taille du fichier). */
  texte_longueur?: number
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

  // Arbre de dossiers des documents indexés (chargement paresseux). prefixe='' = racines.
  tree: (prefixe = '', texte = true) =>
    apiClient.get<{ prefixe: string; dossiers: TreeNode[]; fichiers: TreeFile[] }>(
      '/documents/tree', { params: { prefixe, texte } }
    ).then(r => r.data),

  // Tous les fichiers sous un préfixe (récursif) → « cocher tout le dossier ».
  treeFlat: (prefixe: string, texte = true) =>
    apiClient.get<{ prefixe: string; fichiers: Array<{ id: string; nom: string }> }>(
      '/documents/tree', { params: { prefixe, texte, flat: true } }
    ).then(r => r.data.fichiers),

  // Relance l'IA (tâche durable) → renvoie un job_id à suivre via jobsApi.
  // `route` indique l'aiguillage backend : 'enrich' (texte) ou 'analyze' (média/scan → OCR vision).
  enrich: (id: string) =>
    apiClient.post<{ job_id: string; statut: string; deja?: boolean; route?: 'enrich' | 'analyze' }>(`/documents/${id}/enrich`).then(r => r.data),

  getMetadata: (id: string) =>
    apiClient.get<MetadonneeIA>(`/documents/${id}/metadata`).then(r => r.data),

  patchMetadata: (id: string, data: Partial<Pick<MetadonneeIA, 'tags' | 'categorie' | 'sous_categorie' | 'resume' | 'niveau_confidentialite' | 'mots_cles' | 'entites'>>) =>
    apiClient.patch<MetadonneeIA>(`/documents/${id}/metadata`, data).then(r => r.data),

  getVersions: (id: string) =>
    apiClient.get<{ document_id: string; versions: DocumentVersion[] }>(`/documents/${id}/versions`).then(r => r.data),

  delete: (id: string) =>
    apiClient.delete(`/documents/${id}`).then(r => r.data),

  // dry_run=true → simule (récap sans rien supprimer) ; sinon supprime.
  purgeDoublons: (dryRun = false) =>
    apiClient.post<{
      dry_run: boolean; supprimes?: number; message: string
      nb_groupes?: number; nb_a_supprimer?: number; octets_recuperables?: number
      apercu?: Array<{ type: string; garder: { nom: string; chemin: string; statut: string }; supprimer: Array<{ nom: string; chemin: string }> }>
    }>('/documents/purge-duplicates', null, { params: dryRun ? { dry_run: true } : undefined }).then(r => r.data),

  // Relance l'IA en lot sur les documents extraits mais non enrichis (tâches durables).
  reenrichBatch: () =>
    apiClient.post<{ enqueued: number; message: string }>('/documents/reenrich-batch').then(r => r.data),

  // Analyse le CONTENU d'un doc (média/doc au texte vide), local ou SMB (fetch temporaire, zéro doublon).
  analyze: (id: string) =>
    apiClient.post<{ job_id: string; statut: string; deja?: boolean }>(`/documents/${id}/analyze`).then(r => r.data),

  // Analyse de contenu en lot : scope = empty (docs sans texte) | media (médias) | images (photos
  // cataloguées → description IA vision) | all. `limit` = taille max du lot ; `prefixe` = dossier ciblé.
  analyzeBatch: (scope: 'media' | 'images' | 'empty' | 'all' = 'empty', limit = 1000, prefixe?: string) =>
    apiClient.post<{ enqueued: number; message: string }>('/documents/analyze-batch', null, { params: { scope, limit, prefixe } }).then(r => r.data),
  // Nombre d'images cataloguées sous un dossier (pour cibler la description vision par dossier).
  imagesCount: (prefixe?: string) =>
    apiClient.get<{ images: number; prefixe: string | null }>('/documents/images/count', { params: { prefixe } }).then(r => r.data),

  // Compteurs réels pour les boutons de maintenance.
  maintenanceCounts: () =>
    apiClient.get<{ reenrich: number; sans_texte: number; medias: number; images: number; docs_total: number; enrich_total: number; images_total: number; jobs_enrich: number; jobs_analyze: number }>('/documents/maintenance/counts').then(r => r.data),
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
  // Compteurs RÉELS (COUNT en base, non plafonné) : en cours / en file — pour le badge « Tâches ».
  stats: () =>
    apiClient.get<{ running: number; pending: number; actifs: number }>('/jobs/stats').then(r => r.data),
  get: (id: string) =>
    apiClient.get<JobInfo>(`/jobs/${id}`).then(r => r.data),
  cancel: (id: string) =>
    apiClient.post<{ job_id: string; statut: string }>(`/jobs/${id}/cancel`).then(r => r.data),
  demo: (etapes = 5) =>
    apiClient.post<{ job_id: string; statut: string }>('/jobs/demo', { etapes }).then(r => r.data),
  purgeCount: (days = 365) =>
    apiClient.get<{ total_termines: number; anciens: number; days: number }>('/jobs/purge/count', { params: { days } }).then(r => r.data),
  purge: (scope: 'all' | 'older_than' = 'older_than', days = 365) =>
    apiClient.post<{ supprimes: number; scope: string; days: number | null }>('/jobs/purge', null, { params: { scope, days } }).then(r => r.data),
}

/** Diagnostic du fichier de log : permet de dire POURQUOI la page est vide (au lieu de rien). */
export interface LogsDiagnostic {
  existe?: boolean; taille_octets?: number; lisible?: boolean; erreur?: string | null
  actif?: boolean; erreur_handler?: string | null; aveugle?: boolean; conseil?: string | null
}
export interface LogsTail { lines: string[]; count: number; source: string | null; diagnostic?: LogsDiagnostic }

export const logsApi = {
  tail: (lines = 200) =>
    apiClient.get<LogsTail>('/logs/tail', { params: { lines } }).then(r => r.data),
}

/** Événement d'audit métier (observabilité Phase 2) — relie UI→API→worker par correlation_id. */
export interface AuditEvent {
  id: string; correlation_id: string | null; acteur: string; action: string
  cible: string | null; statut: string; duree_ms: number | null
  message: string | null; detail: Record<string, unknown> | null; created_at: string | null
}
export const auditApi = {
  list: (params?: { action?: string; statut?: string; acteur?: string; correlation_id?: string; limit?: number }) =>
    apiClient.get<{ events: AuditEvent[] }>('/audit', { params }).then(r => r.data.events),
  actions: () =>
    apiClient.get<{ actions: string[] }>('/audit/actions').then(r => r.data.actions),
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

// Doublons parmi les fichiers INDEXÉS (hash exact + quasi-doublons IA)
export interface IndexedDupFile { id: string; nom: string; chemin: string; source: string; taille_octets: number; garder: boolean }
export interface IndexedDupGroup { type: 'hash' | 'ia'; cle: string; score: number; fichiers: IndexedDupFile[] }
export interface IndexedDupResponse {
  groupes: IndexedDupGroup[]; nb_groupes: number; nb_fichiers: number
  octets_recuperables: number; note: string | null
}

export const duplicatesApi = {
  // Scan disque : potentiellement long → client à timeout étendu
  scan: () => apiClientLong.get<DuplicatesResponse>('/duplicates').then(r => r.data),

  quarantine: (chemins: string[]) =>
    apiClient.post<QuarantineResponse>('/duplicates/quarantine', { chemins }).then(r => r.data),

  // Doublons des fichiers indexés (hash + IA), périmètre par préfixe de chemin
  indexed: (opts: { prefixe?: string; mode?: 'hash' | 'ia' | 'both'; seuil?: number } = {}) =>
    apiClientLong.get<IndexedDupResponse>('/duplicates/indexed', {
      params: { prefixe: opts.prefixe, mode: opts.mode ?? 'both', seuil: opts.seuil },
    }).then(r => r.data),

  // Images floues (variance du Laplacien) : seuil = netteté minimale
  blurry: (seuil = 100) =>
    apiClientLong.get<{ images: BlurryImage[]; nb: number; seuil: number }>('/duplicates/blurry', {
      params: { seuil },
    }).then(r => r.data),
}

export interface BlurryImage { chemin: string; relatif: string; nom: string; taille_octets: number; nettete: number }

// ─── Liens documentaires (BC ↔ facture) ────────────────────────────────────────

export interface LinkedDoc { id: string; nom: string; chemin: string | null; existe: boolean }
export interface DocumentLink {
  id: string
  type_lien: string        // 'bc_facture' | 'reference' | 'manuel'
  reference: string | null
  score: number
  statut: 'suggere' | 'valide' | 'rejete'
  origine: 'auto' | 'manuel'
  source: LinkedDoc
  cible: LinkedDoc
}

export const linksApi = {
  // Détecte les paires partageant une référence et enregistre les nouvelles suggestions
  scan: (prefixe?: string) =>
    apiClientLong.post<{ documents_analyses: number; suggestions_trouvees: number; nouvelles: number }>(
      '/links/scan', { prefixe },
    ).then(r => r.data),

  list: (statut?: 'suggere' | 'valide' | 'rejete') =>
    apiClient.get<{ liens: DocumentLink[]; nb: number }>('/links', { params: { statut } }).then(r => r.data),

  forDocument: (id: string) =>
    apiClient.get<{ liens: DocumentLink[]; nb: number }>(`/links/document/${id}`).then(r => r.data),

  createManual: (source_document_id: string, cible_document_id: string, type_lien = 'manuel') =>
    apiClient.post<DocumentLink>('/links', { source_document_id, cible_document_id, type_lien }).then(r => r.data),

  validate: (id: string) => apiClient.post<DocumentLink>(`/links/${id}/validate`).then(r => r.data),
  reject: (id: string) => apiClient.post<DocumentLink>(`/links/${id}/reject`).then(r => r.data),
  remove: (id: string) => apiClient.delete<{ supprime: boolean }>(`/links/${id}`).then(r => r.data),
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

  // Remplissage d'un template DOCX = tâche durable → job_id à suivre (suivreJob), puis download.
  fillTemplate: (request: { document_ids: string[]; template_id: string; instructions?: string; model?: string }) =>
    apiClient.post<{ job_id: string; statut: string }>('/generate/fill-template', request).then(r => r.data),

  fillTemplateDownloadUrl: (jobId: string) => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/generate/fill-template/download/${jobId}`
  },
}

// ─── Export ──────────────────────────────────────────────────────────────────

// ─── Historique des rapports (archive persistante) ─────────────────────────────
export interface RapportSource { id: string; nom: string }
export interface RapportResume {
  id: string; titre: string; mode?: string | null; prompt?: string | null
  modele?: string | null; nb_caracteres: number; sources: RapportSource[]; created_at?: string | null
}
export interface RapportDetail extends RapportResume { contenu: string }

export const rapportsApi = {
  list: (limit = 100) =>
    apiClient.get<{ total: number; rapports: RapportResume[] }>('/rapports', { params: { limit } }).then(r => r.data),
  get: (id: string) =>
    apiClient.get<RapportDetail>(`/rapports/${id}`).then(r => r.data),
  remove: (id: string) =>
    apiClient.delete<{ supprimes: number }>(`/rapports/${id}`).then(r => r.data),
  // Suppression en lot : une sélection d'ids, ou tout l'historique (tout=true).
  removeMany: (ids: string[], tout = false) =>
    apiClient.post<{ supprimes: number }>('/rapports/delete', { ids, tout }).then(r => r.data),
}

// ─── Connecteurs cloud (Google Drive…) ─────────────────────────────────────────
export interface CompteConnecteur { id: string; type: string; libelle: string; identifiant?: string | null; chemin_base?: string | null }
export const connectorsApi = {
  comptes: () =>
    apiClient.get<{ comptes: CompteConnecteur[] }>('/connectors/comptes').then(r => r.data.comptes),
  // Démarre la connexion OAuth : renvoie l'URL de consentement Google à ouvrir.
  oauthStart: (libelle = 'Google Drive') =>
    apiClient.get<{ url: string; redirect_uri: string }>('/connectors/oauth/start', { params: { libelle } }).then(r => r.data),
  remove: (id: string) =>
    apiClient.delete(`/sources/${id}`).then(r => r.data),
  index: (id: string, chemin = '/') =>
    apiClient.post<{ job_id: string }>(`/connectors/${id}/index`, null, { params: { chemin } }).then(r => r.data),
  // Teste la connexion d'un compte (auth + joignabilité) → pastille verte/rouge.
  test: (id: string) =>
    apiClientLong.post<{ ok: boolean }>(`/connectors/${id}/test`).then(r => r.data),
  // Crée un compte connecteur à identifiants (WebDAV, Synology…) — secret chiffré côté backend.
  createCredential: (body: {
    type: string; libelle: string; hote: string; identifiant: string; mot_de_passe: string; chemin_base?: string
  }) => apiClient.post<CompteConnecteur>('/connectors', body).then(r => r.data),
  // Appaire un compte reMarkable via son code à usage unique (my.remarkable.com/device/desktop).
  remarkablePair: (code: string, libelle = 'reMarkable') =>
    apiClientLong.post<CompteConnecteur>('/connectors/remarkable/pair', { code, libelle }).then(r => r.data),
}

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

// Étiquette de pertinence ABSOLUE — remplace le % à l'affichage, qui est relatif au lot
// (le meilleur résultat vaut toujours ~100 %, même quand tout le lot est hors-sujet).
export type Etiquette = 'elevee' | 'moyenne' | 'faible'

export interface SearchResponse {
  query: string
  type: string
  total: number
  offset: number
  limit: number
  has_more: boolean
  nb_pertinents: number   // 0 → « Aucun document pertinent » (le reste est proposable)
  nb_masques: number
  seuils?: { haut: number; bas: number }
  resultats: Array<{
    id: string
    nom: string
    extension: string
    type_groupe?: string   // catégorie large (PDF, Document, Image, Audio…) pour regrouper/filtrer
    taille_octets?: number
    statut: string
    chemin_copie?: string
    score: number
    pertinence?: number | null  // ③ pertinence ABSOLUE 0-100 (cosinus brut) — tranches GED
    pertinent?: boolean         // passe le gate absolu (cf. backend services/pertinence.py)
    etiquette?: Etiquette
    wiki_url?: string      // lien BookStack si le doc vient du wiki (carte spécifique « livre »)
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
  criteres_auto: boolean
  stream_url: string
}

/** Formats de sortie du comparatif — choisis APRÈS génération (aucun appel IA re-déclenché). */
export type CompareFormat = 'xlsx' | 'pdf' | 'docx' | 'md'

export interface CompareResultat {
  job_id: string
  colonnes: string[]
  groupes: { nom: string; valeurs: Record<string, string> }[]
  synthese: string | null
  markdown: string
  formats: CompareFormat[]
}

export const compareApi = {
  start: (request: {
    groupes: { nom: string; document_ids: string[] }[]
    /** Facultatif — sans template ni colonnes, l'IA déduit les critères. */
    template_id?: string
    colonnes?: string[]
    model?: string
    instructions?: string
    synthese?: boolean
  }) => apiClientLong.post<CompareResponse>('/generate/compare', request).then(r => r.data),

  /** Fait proposer par l'IA des critères de comparaison à partir de documents. */
  proposerCriteres: (request: { document_ids: string[]; instructions?: string; model?: string }) =>
    apiClientLong.post<{ colonnes: string[]; model: string }>('/generate/compare/criteres', request)
      .then(r => r.data),

  getResultat: (jobId: string) =>
    apiClient.get<CompareResultat>(`/generate/compare/resultat/${jobId}`).then(r => r.data),

  getStreamUrl: (jobId: string) => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/generate/compare/stream/${jobId}`
  },

  getDownloadUrl: (jobId: string, format: CompareFormat = 'xlsx') => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/generate/compare/download/${jobId}?format=${format}`
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

export interface ServiceStatus { url: string; ok: boolean; etat?: 'ok' | 'busy' | 'down' }
export interface BookStackStatus extends ServiceStatus { configure?: boolean }
export interface TranscriptionStatus extends ServiceStatus { configure?: boolean }
export interface ServicesStatus { tika: ServiceStatus; ollama: ServiceStatus; n8n: ServiceStatus; clamav?: ServiceStatus; bookstack?: BookStackStatus; transcription?: TranscriptionStatus }
export interface ModelInfo {
  role: string; resume: string; ecriture_fr: string; vitesse: string
  vram: string; verdict: string; taille_go: number; connu: boolean
}
export interface OllamaModel {
  name: string; size: number; digest?: string
  famille?: string | null; parametres?: string | null
  update?: boolean | null   // true = MAJ dispo, false = à jour, null = inconnu (compat)
  // Statut de vérification lisible : à jour · MAJ dispo · hors registre (import perso) · registre injoignable.
  update_statut?: 'a_jour' | 'maj_dispo' | 'absent' | 'injoignable'
  classe?: 'officiel' | 'uncensored'   // classification PERSISTÉE (registre/catalogue)
  info?: ModelInfo          // descriptif + évaluation (icône « i » + tableau comparatif)
}
export interface PullProgress { status: string; completed?: number; total?: number; error?: string }
export interface ConfigEntry { valeur: string; source: 'base' | 'env'; defini?: boolean }
/**
 * Antivirus. Trois populations à ne jamais confondre : `sain` (examiné, rien trouvé),
 * `non_scanne` (trop gros pour clamd ou clamd muet — INDEXÉ SANS ÊTRE EXAMINÉ), et
 * `inconnu` (indexé avant que l'application ne sache distinguer les deux, < v1.79.0).
 */
export interface AntivirusTableau {
  service: { actif: boolean; joignable: boolean; adresse: string | null }
  /** Limite INSTREAM de clamd : au-delà, il REFUSE de scanner, quel que soit l'état fiché. */
  limite: { octets: number; mo: number; documents_au_dessus: number; octets_au_dessus: number }
  total_documents: number
  repartition: Record<string, { documents: number; octets: number }>
  /** non_scanne + inconnu : le nombre de documents dont on ne peut rien affirmer. */
  a_examiner: number
  /**
   * Fichiers concernés, par état ACTIONNABLE (`infecte`, `non_scanne`, `desactive`).
   * `sain` n'y figure pas : lister 60 000 documents corrects n'apprend rien.
   * `detail` porte la signature ClamAV pour un fichier infecté.
   */
  apercus: Record<string, { id: string; nom: string; chemin: string; taille_octets: number; detail: string | null }[]>
}

export interface SystemConfig {
  tika_url: ConfigEntry; ollama_url: ConfigEntry; n8n_url: ConfigEntry; default_model: ConfigEntry
  bookstack_url?: ConfigEntry; bookstack_token_id?: ConfigEntry; bookstack_token_secret?: ConfigEntry
  huggingface_token?: ConfigEntry; huggingface_user?: ConfigEntry; huggingface_password?: ConfigEntry
  gdrive_client_id?: ConfigEntry; gdrive_client_secret?: ConfigEntry
  dropbox_app_key?: ConfigEntry; dropbox_app_secret?: ConfigEntry
  transcription_url?: ConfigEntry; transcription_model?: ConfigEntry
  transcription_langue?: ConfigEntry; transcription_api_key?: ConfigEntry
  usage_models?: ConfigEntry
  admin_links?: ConfigEntry
  acronymes?: ConfigEntry
  search_cos_haut?: ConfigEntry; search_cos_bas?: ConfigEntry
  backup_auto_heures?: ConfigEntry; backup_retention?: ConfigEntry
  rapports_purge_jours?: ConfigEntry
  concurrence_gpu?: ConfigEntry; concurrence_io?: ConfigEntry
  prewarm_enabled?: ConfigEntry
  parents_date_terme?: ConfigEntry   // AAAA-MM-JJ — ancre du rétroplanning « Devenir parent »
  // Fiche de l'utilisateur — au niveau de l'APPLICATION, pas d'un module : une adresse
  // sert à une distance, à un contrat, à un point sur une carte.
  profil_adresse?: ConfigEntry
  profil_code_postal?: ConfigEntry
  profil_ville?: ConfigEntry
  profil_email?: ConfigEntry
  profil_telephone?: ConfigEntry
  ha_url?: ConfigEntry; ha_token?: ConfigEntry   // Home Assistant (LAN) — diffusion
}
export interface ConfigUpdate {
  tika_url?: string; ollama_url?: string; n8n_url?: string; default_model?: string
  bookstack_url?: string; bookstack_token_id?: string; bookstack_token_secret?: string
  huggingface_token?: string; huggingface_user?: string; huggingface_password?: string
  gdrive_client_id?: string; gdrive_client_secret?: string
  dropbox_app_key?: string; dropbox_app_secret?: string
  transcription_url?: string; transcription_model?: string
  transcription_langue?: string; transcription_api_key?: string
  usage_models?: string   // JSON {usage: modele}
  admin_links?: string    // JSON [{section, label, url}]
  acronymes?: string      // JSON [{sigle, definition}]
  search_cos_haut?: string; search_cos_bas?: string   // seuils cosinus 0-1
  backup_auto_heures?: string; backup_retention?: string   // sauvegarde auto
  rapports_purge_jours?: string   // purge auto de l'historique des rapports (0 = jamais)
  concurrence_gpu?: string; concurrence_io?: string   // concurrence worker (GPU / I/O)
  prewarm_enabled?: string   // "1"/"0" — garder le modèle de rapport chaud en VRAM
  parents_date_terme?: string   // AAAA-MM-JJ — ancre du rétroplanning « Devenir parent »
  profil_adresse?: string
  profil_code_postal?: string
  profil_ville?: string
  profil_email?: string
  profil_telephone?: string
  ha_url?: string; ha_token?: string   // Home Assistant : URL du LAN + jeton (chiffré)
}
export interface AdminLink { section: string; label: string; url: string }
export type StatutLien = 'ok' | 'deplace' | 'mort' | 'injoignable'
export interface LienVerif { url: string; statut: StatutLien; code: number | null; url_finale?: string }

// ─── Sources (local / SMB) ────────────────────────────────────────────────────

export interface Source {
  id: string; libelle: string; type: 'local' | 'smb' | 'gdrive'
  chemin_base?: string | null; hote?: string | null; domaine?: string | null
  identifiant?: string | null; secret_defini: boolean; actif: boolean
  /** Synchro automatique : intervalle en minutes (null/0 = désactivée). */
  sync_intervalle_minutes?: number | null
  dernier_sync?: string | null
  /** Récap du dernier diff, une entrée par périmètre synchronisé. */
  dernier_sync_recap?: Record<string, SyncRecap> | null
}
export interface SyncRecap {
  nouveaux: number; modifies: number; absents: number; deplaces: number
  revenus: number; inchanges: number; traites: number; annule: boolean; date?: string
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
  // Re-scanne les dossiers déjà indexés de la source (rattrape les nouveautés, idempotent).
  reindex: (id: string) =>
    apiClient.post<{ job_ids: string[]; nb: number; message: string }>(`/sources/${id}/reindex`).then(r => r.data),
  // Synchro INCRÉMENTALE : ne traite que les écarts (nouveaux/modifiés/déplacés/disparus).
  // Sans changement, aucun fichier n'est téléchargé et l'IA n'est pas sollicitée.
  sync: (id: string) =>
    apiClient.post<{ job_ids: string[]; nb: number; message: string }>(`/sources/${id}/sync`).then(r => r.data),
  // Règle la synchro AUTOMATIQUE (intervalle en minutes ; 0 = désactivée).
  setSyncConfig: (id: string, intervalle_minutes: number | null) =>
    apiClient.patch<Source>(`/sources/${id}/sync-config`, { intervalle_minutes }).then(r => r.data),
  // Documents 'absent' (disparus du NAS) d'une source, et purge de l'index (ne touche aux fichiers).
  absents: (id: string) =>
    apiClient.get<{ total: number; documents: Array<{ id: string; nom: string; chemin: string; date: string | null }> }>(`/sources/${id}/absents`).then(r => r.data),
  purgeAbsents: (id: string, ids: string[], tout = false) =>
    apiClient.post<{ retires: number }>(`/sources/${id}/purge-absents`, { ids, tout }).then(r => r.data),
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
  // Le backend écarte déjà les documents hors-sujet (gate de pertinence) : une pièce peut
  // donc légitimement ressortir sans aucun document.
  documents: Array<{
    id: string; nom: string; extension: string; categorie?: string | null
    score: number; etiquette?: Etiquette
  }>
}

// Q&R « Poser une question » (E8) : réponse textuelle ancrée + documents justificatifs.
export type Confiance = 'Élevée' | 'Moyenne' | 'Faible'
export interface QADocument {
  id: string; nom: string; extension: string
  categorie?: string | null; employeur?: string | null; periode?: string | null
  score?: number | null; pertinence?: number | null   // pertinence 0-100 (cosinus absolu)
}
export interface QAReponse {
  question: string
  intent: { intent: string; personnes: string[]; organisations: string[]; type_piece: string[] }
  reponse: string            // vide si aucun fait ancré → voir `approchant`
  confiance: Confiance
  documents: QADocument[]
  approchant: boolean        // true → réponse vide, `documents` = candidats approchants (repli honnête)
}

export const assistantApi = {
  // Déduit les pièces attendues d'un besoin + propose les fichiers (LLM + recherche → lent)
  pieces: (besoin: string, model?: string) =>
    apiClientLong.post<{ besoin: string; pieces: PieceProposee[] }>(
      '/assistant/pieces', { besoin, model }
    ).then(r => r.data),
  // Répond à une question NL par une réponse ancrée + documents (plusieurs appels LLM → lent)
  question: (question: string, model?: string) =>
    apiClientLong.post<QAReponse>('/assistant/question', { question, model }).then(r => r.data),
}

// Dialogue LIBRE avec l'IA (aide à la rédaction, questions…), sans lien avec la GED.
export type ChatMessage = { role: 'system' | 'user' | 'assistant'; content: string }
export const chatApi = {
  // Streaming : appelle `onChunk` au fil de l'eau, renvoie la réponse complète. `model` vide = défaut
  // Paramètres. `useGed=true` → l'IA reçoit des extraits de la GED en contexte (RAG).
  stream: async (
    messages: ChatMessage[], model: string | undefined, useGed: boolean,
    onChunk: (t: string) => void, signal?: AbortSignal,
  ): Promise<string> => {
    const base = import.meta.env.VITE_API_URL ?? ''
    const res = await fetch(`${base}/api/generate/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, model: model || undefined, use_ged: useGed }),
      signal,
    })
    if (!res.ok || !res.body) throw new Error(`chat HTTP ${res.status}`)
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let full = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value, { stream: true })
      if (chunk) { full += chunk; onChunk(chunk) }
    }
    return full
  },
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

export interface OrganizeDoc { id: string; nom: string; categorie?: string; chemin_actuel?: string }
export interface OrganizeFolder { dossier: string; nb: number; documents: OrganizeDoc[] }
export interface OrganizeProposal {
  criteres: string; consigne: string | null
  nb_documents: number; nb_dossiers: number; arborescence: OrganizeFolder[]
}

export interface OrganizePlan { nb_dossiers: number; nb_documents: number; arborescence: OrganizeFolder[]; peut_annuler?: boolean }

export interface OrganizeMove { id: string; nom: string; source: string; dest: string | null; taille?: number; warn: string | null }
export interface OrganizeDryRun { total: number; a_deplacer: number; ignores: number; volume: number; moves: OrganizeMove[] }
export interface OrganizeScope { consigne?: string; inclure_annee?: boolean; source_id?: string; chemin_prefixe?: string }

export const organizeApi = {
  propose: (opts: OrganizeScope = {}) =>
    apiClientLong.post<OrganizeProposal>('/organize/propose', {
      consigne: opts.consigne,
      inclure_annee: opts.inclure_annee ?? true,
      source_id: opts.source_id,
      chemin_prefixe: opts.chemin_prefixe,
    }).then(r => r.data),
  getPlan: () =>
    apiClient.get<OrganizePlan>('/organize/plan').then(r => r.data),
  movePlan: (document_ids: string[], dossier_cible: string) =>
    apiClient.post<{ deplaces: number; dossier_cible: string }>('/organize/plan/move', { document_ids, dossier_cible }).then(r => r.data),
  dryRun: () =>
    apiClientLong.post<OrganizeDryRun>('/organize/apply/dry-run').then(r => r.data),
  apply: () =>
    apiClient.post<{ job_id: string; batch_id: string; statut: string }>('/organize/apply').then(r => r.data),
  undo: () =>
    apiClient.post<{ job_id: string; batch_id: string; statut: string }>('/organize/undo').then(r => r.data),
}

// ─── BookStack (publication wiki) ─────────────────────────────────────────────

export interface BookStackBook { id: number; name: string; slug?: string }
export interface BookStackChapter { id: number; name: string; book_id?: number }
export interface BookStackShelf { id: number; name: string; slug?: string }
export interface BookStackTargets { books: BookStackBook[]; chapters: BookStackChapter[]; shelves: BookStackShelf[] }
export interface PublishResult { success: boolean; page_id: number; page_url: string; titre: string; shelf_id?: number | null }

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
  /** Étagère existante où ranger le livre (optionnel) */
  shelf_id?: number
  /** Nom d'une étagère à créer (optionnel) */
  new_shelf?: string
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

// ─── Passerelle de publication (projets & jetons entrants) ────────────────────

export interface PasserelleProjet {
  nom: string
  livres_autorises: string[]
  actif: boolean
  created_at: string | null
  last_used_at: string | null
}
/** Réponse de création/rotation : le jeton en clair n'est renvoyé QU'UNE seule fois. */
export interface PasserelleJeton extends Partial<PasserelleProjet> {
  nom: string
  jeton: string
  avertissement: string
}

export const passerelleApi = {
  // Liste les projets publieurs (jamais le hash du jeton)
  projets: () =>
    apiClient.get<{ projets: PasserelleProjet[] }>('/passerelle/projets').then(r => r.data.projets),
  // Crée un projet + génère son jeton (montré 1×)
  creer: (nom: string, livres_autorises: string[]) =>
    apiClient.post<PasserelleJeton>('/passerelle/projets', { nom, livres_autorises }).then(r => r.data),
  // Rotation du jeton (l'ancien cesse immédiatement)
  regenerer: (nom: string) =>
    apiClient.post<PasserelleJeton>(`/passerelle/projets/${encodeURIComponent(nom)}/regenerer`).then(r => r.data),
  // (Dés)activer / modifier la liste blanche des livres
  modifier: (nom: string, patch: { actif?: boolean; livres_autorises?: string[] }) =>
    apiClient.patch<PasserelleProjet>(`/passerelle/projets/${encodeURIComponent(nom)}`, patch).then(r => r.data),
}

export const systemApi = {
  // Version applicative (source de vérité = fichier VERSION côté backend)
  version: () =>
    apiClient.get<{ name: string; version: string }>('/version').then(r => r.data),

  // Statut live des services (via backend → fiable derrière le proxy)
  services: () =>
    apiClient.get<ServicesStatus>('/system/services').then(r => r.data),

  // Le modèle d'un usage est-il chargé en mémoire (génération instantanée) ou à froid ?
  modelStatus: (usage = 'rapport') =>
    apiClient.get<{ usage: string; modele: string; charge: boolean }>('/system/model-status', { params: { usage } }).then(r => r.data),
  // Pré-charge le modèle (« Préparer ») pour éviter l'attente de chargement à la génération.
  warmModel: (usage = 'rapport') =>
    apiClientLong.post<{ usage: string; modele: string; ok: boolean; charge: boolean; duree_ms: number }>('/system/warm-model', null, { params: { usage } }).then(r => r.data),

  // Pause / reprise de l'IA (le worker cesse de réclamer les tâches Ollama → libère le GPU).
  iaStatus: () =>
    apiClient.get<{ pause: boolean; en_cours: number }>('/system/ia/status').then(r => r.data),
  iaPause: (pause: boolean, annuler = false) =>
    apiClient.post<{ pause: boolean; annulees: number }>('/system/ia/pause', { pause, annuler }).then(r => r.data),

  getConfig: () =>
    apiClient.get<{ config: SystemConfig }>('/system/config').then(r => r.data.config),

  updateConfig: (data: ConfigUpdate) =>
    apiClient.put<{ config: SystemConfig; mis_a_jour: string[] }>('/system/config', data).then(r => r.data),

  /** Tableau de bord antivirus : ce qui a été examiné, et surtout ce qui ne l'a pas été. */
  antivirus: () =>
    apiClient.get<AntivirusTableau>('/system/antivirus').then(r => r.data),

  // Catalogue de services publics activables (piloté par la config, rechargeable).
  getAdminCatalogue: () =>
    apiClient.get<{ catalogue: AdminLink[] }>('/system/admin-catalogue').then(r => r.data.catalogue),

  // Vérifie l'état des liens Administration — SORTIE RÉSEAU (n'envoie que les URLs).
  verifierLiens: (urls: string[]) =>
    apiClient.post<{ resultats: LienVerif[] }>('/system/admin-links/verifier', { urls }).then(r => r.data.resultats),

  testService: (service: 'tika' | 'ollama' | 'n8n' | 'bookstack' | 'huggingface' | 'transcription' | 'ha', overrides?: ConfigUpdate) =>
    apiClient.post<{ service: string; url?: string; ok: boolean; configure?: boolean; user?: string; type?: string; erreur?: string }>(`/system/test/${service}`, overrides ?? {}).then(r => r.data),

  // Modèles Ollama installés (dynamique) — alimente le sélecteur + Paramètres
  models: (checkUpdates = false) =>
    apiClient.get<{ models: OllamaModel[]; defaut: string; par_usage?: Record<string, string> }>('/system/models', {
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

  // Normalise la casse/accents des tags & catégories (fusionne les variantes ; sigles → MAJ).
  // Réversible (backup côté serveur). Long → apiClientLong.
  normaliserMetadata: () =>
    apiClientLong.post<{ ok: boolean; resume: Record<string, number> }>('/system/normaliser-metadata').then(r => r.data),

  // Sauvegarde de la base (pg_dump) → fichier dans storage/backups/. Long.
  backupDb: () =>
    apiClientLong.post<{ ok: boolean; fichier: string; taille_octets: number; date: string }>('/system/backup-db').then(r => r.data),

  listBackups: () =>
    apiClient.get<{ backups: Array<{ fichier: string; taille_octets: number; date: string; dossier?: string }> }>('/system/backups').then(r => r.data.backups),
  // URL de téléchargement d'un fichier de sauvegarde (lien direct → proxy).
  backupDownloadUrl: (fichier: string) => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/system/backups/${encodeURIComponent(fichier)}`
  },
}

// ─── Regroupements de documents (analyses persistantes) ───────────────────────
export interface RegroupementResume {
  id: string
  nom: string
  description?: string | null
  nb_documents: number
  prompt?: string | null
  modele?: string | null
  dernier_analyse_at?: string | null
  dernier_modele?: string | null
}
export interface RegroupementDetail extends RegroupementResume {
  documents: Array<{ id: string; nom: string; extension?: string | null }>
  dernier_rendu?: string | null
}

export const regroupementsApi = {
  list: () =>
    apiClient.get<{ regroupements: RegroupementResume[] }>('/regroupements').then(r => r.data.regroupements),
  get: (id: string) =>
    apiClient.get<RegroupementDetail>(`/regroupements/${id}`).then(r => r.data),
  create: (data: { nom: string; description?: string; document_ids: string[]; prompt?: string; modele?: string }) =>
    apiClient.post<RegroupementResume>('/regroupements', data).then(r => r.data),
  update: (id: string, data: Partial<{ nom: string; description: string; document_ids: string[]; prompt: string; modele: string }>) =>
    apiClient.put<RegroupementResume>(`/regroupements/${id}`, data).then(r => r.data),
  remove: (id: string) =>
    apiClient.delete(`/regroupements/${id}`).then(r => r.data),
  // Analyse = tâche durable → renvoie un job_id à suivre (suivreJob).
  analyser: (id: string, prompt?: string, model?: string) =>
    apiClient.post<{ job_id: string; statut: string }>(`/regroupements/${id}/analyser`, { prompt, model }).then(r => r.data),
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

export interface HfModelDetail {
  ok: boolean
  id: string
  resume?: string
  resume_ia?: boolean
  resume_en?: string
  pipeline_tag?: string | null
  license?: string | null
  downloads?: number
  likes?: number
  gated?: boolean
  gguf?: boolean
  tags?: string[]
  ollama_ref?: string
  erreur?: string
}

export const huggingfaceApi = {
  // Appel réseau HF — à déclencher uniquement sur confirmation (garde-fou 100% local).
  catalog: (params: HfCatalogParams) =>
    apiClient.get<HfCatalog>('/huggingface/catalog', { params }).then(r => r.data),
  model: (id: string) =>
    apiClient.get<HfModelDetail>('/huggingface/model', { params: { id } }).then(r => r.data),
}

// --- Wiki (livres BookStack, lecture) ---
export interface WikiBook {
  id: number; name: string; slug?: string; description: string
  updated_at?: string; has_cover: boolean; cover_url: string | null
}
export interface WikiContentItem {
  type: 'chapter' | 'page'; id: number; name: string; slug?: string
  pages?: { id: number; name: string; slug?: string }[]
}
export interface WikiBookDetail {
  id: number; name: string; slug?: string; description: string
  contents: WikiContentItem[]; url: string; has_cover: boolean
}
export interface WikiPageContent { id: number; name: string; html: string; url: string }
export interface WikiShelf { id: number; name: string; book_ids: number[] }

export const wikiApi = {
  books: () => apiClient.get<{ configured: boolean; base_url: string; books: WikiBook[]; shelves: WikiShelf[] }>('/wiki/books').then(r => r.data),
  book: (id: number) => apiClient.get<WikiBookDetail>(`/wiki/books/${id}`).then(r => r.data),
  page: (id: number) => apiClient.get<WikiPageContent>(`/wiki/pages/${id}`).then(r => r.data),
  index: () => apiClient.post<{ job_id: string; statut: string }>('/wiki/index').then(r => r.data),
  // Gestion depuis Matothèque (répercuté direct dans BookStack, sans étape de synchro)
  renommerLivre: (id: number, name: string) =>
    apiClient.patch<{ id: number; name: string }>(`/wiki/books/${id}`, { name }).then(r => r.data),
  renommerEtagere: (id: number, name: string) =>
    apiClient.patch<{ id: number; name: string }>(`/wiki/shelves/${id}`, { name }).then(r => r.data),
  deplacerLivre: (id: number, from_shelf_id: number | null, to_shelf_id: number | null) =>
    apiClient.post<{ ok: boolean }>(`/wiki/books/${id}/deplacer`, { from_shelf_id, to_shelf_id }).then(r => r.data),
}

// ─── Dossiers thématiques — veille par sujet ──────────────────────────────────
// Ressources EXTERNES (podcasts, docs, livres, études) rassemblées par sujet. À ne pas
// confondre avec les Liens, qui relient des documents indexés entre eux.

export interface Ressource {
  id: string
  dossier_id: string
  titre: string
  auteur: string | null
  type: string          // voir dossiersApi.types() — liste servie par le backend
  url: string | null
  langue: string        // 'fr' | 'en' | …
  groupe: string | null
  note: string | null
  contenu: string | null   // texte long intégral (prompt à copier, extrait, mode d'emploi)
  /** Proposition de résumé par l'IA locale — persistée, éditable, DISTINCTE de `note`. */
  resume_ia: string | null
  /** URL du FLUX (podcast) — distincte de `url`, qui pointe la page de l'émission. */
  flux_url: string | null
  tags: string[]
  position: number
  favori: boolean
  active: boolean
}

export interface DossierResume {
  id: string
  titre: string
  slug: string
  description: string | null
  origine: string       // 'manuel' | 'seed:<cle>'
  parent_id: string | null      // null = dossier racine ; sinon = sous-dossier
  nb_ressources: number
  nb_sous_dossiers: number
  // CAPACITÉS du dossier : { 'emploi-domicile': { profil: 'assmat' } }. C'est ce qui fait
  // apparaître un onglet supplémentaire — jamais un test sur le slug.
  modules: Record<string, Record<string, string>>
  created_at: string | null
  updated_at: string | null
}

export interface DossierDetail extends DossierResume {
  parent: { id: string; titre: string; slug: string } | null   // fil d'Ariane
  sous_dossiers: DossierResume[]
  groupes: string[]     // ordre d'apparition = progression voulue, pas alphabétique
  ressources: Ressource[]
}

export interface SeedDisponible { cle: string; titre: string; nb: number; hierarchique?: boolean }

// Destination possible pour déplacer une ressource (toute la « famille » du dossier, indentée).
export interface CibleDeplacement { id: string; titre: string; slug: string; profondeur: number }

// Veille RSS : un dossier peut s'abonner à des flux ; les nouveautés arrivent en items à promouvoir.
export interface FluxRss {
  id: string
  url: string
  titre: string | null
  actif: boolean
  dernier_fetch: string | null
  dernier_etat: string | null   // 'ok' | 'erreur: …'
  non_lus: number
}

export interface VeilleItem {
  id: string
  flux_id: string
  source: string | null         // titre du flux d'origine
  titre: string
  url: string | null
  auteur: string | null
  resume: string | null
  date_pub: string | null
  lu: boolean
  promu: boolean
}

export type RessourceInput = {
  titre: string; auteur?: string | null; type?: string; url?: string | null
  /** `null` efface la proposition en base (ce que fait « Supprimer »). */
  resume_ia?: string | null
  flux_url?: string | null
  langue?: string; groupe?: string | null; note?: string | null; contenu?: string | null
  tags?: string[]; favori?: boolean; active?: boolean
}

/**
 * Jalon d'un rétroplanning. `mois` est un entier SIGNÉ : négatif = mois de grossesse
 * (-9 = 1ᵉʳ mois, -1 = 9ᵉ), 0 et au-delà = âge de l'enfant en mois. Un seul champ pour
 * les deux versants — c'est ce qui permet de calculer les fenêtres avec une seule formule.
 */
export interface Jalon {
  id: string
  dossier_id: string
  mois: number
  sa: number | null          // semaines d'aménorrhée, quand l'échéance se dit ainsi
  /** Date d'un rendez-vous PRIS. Prime sur `sa` et `mois` — cf. `date_prevue`. */
  date_reelle: string | null
  /** Créneau « HH:MM ». Heures locales flottantes, jamais converties de fuseau. */
  heure_debut: string | null
  heure_fin: string | null
  titre: string
  detail: string | null
  categorie: string          // voir Planning.categories
  echeance: string | null    // formulation exacte quand elle est réglementaire
  url: string | null
  obligatoire: boolean
  position: number
  origine: string            // 'manuel' | 'seed:<cle>'
  fait: boolean
  fait_le: string | null
  note_perso: string | null
  /**
   * Date où poser le jalon sur un calendrier : `date_reelle` si elle existe, sinon calculée
   * depuis le terme (null tant qu'aucun terme n'est saisi et qu'aucune date n'est fixée).
   */
  date_prevue: string | null
  /** true = date au jour près (rendez-vous pris, ou déduite des SA) ; false = début de mois. */
  date_precise: boolean
}

export interface PlanningMois {
  index: number
  phase: 'grossesse' | 'enfant'
  libelle: string
  debut: string | null       // null tant qu'aucune date de terme n'est saisie
  fin: string | null
  jalons: Jalon[]
}

export interface Planning {
  dossier: { id: string; slug: string; titre: string }
  date_terme: string | null
  avertissement: string
  categories: Record<string, string>
  stats: { total: number; faits: number; obligatoires: number; obligatoires_faits: number }
  mois: PlanningMois[]
}

export type JalonInput = {
  /** Facultatif dès qu'une `date_reelle` est fournie : le backend le déduit du terme. */
  mois?: number | null
  titre: string; detail?: string | null; categorie?: string
  echeance?: string | null; url?: string | null; sa?: number | null; obligatoire?: boolean
  date_reelle?: string | null; heure_debut?: string | null; heure_fin?: string | null
}

/**
 * Proposition d'événement rendue par l'IA locale à partir d'un texte libre.
 * C'est une SUGGESTION : elle pré-remplit le formulaire, rien n'est enregistré.
 */
export interface PropositionJalon {
  titre: string
  detail: string | null
  categorie: string
  date_reelle: string | null
  heure_debut: string | null
  heure_fin: string | null
  obligatoire: boolean
  /** Mois déduit de la date par le backend, quand le terme est connu. */
  mois?: number
}

export interface EpisodePodcast {
  titre: string
  date_pub: string | null
  /** Durée en secondes, quand l'éditeur la publie. */
  duree: number | null
  audio_url: string
  audio_type: string | null
  audio_octets: number
  page: string | null
}
export interface EpisodesPodcast {
  titre_flux: string | null
  episodes: EpisodePodcast[]
  /** Items du flux sans audio (un flux mixte articles/épisodes en contient). */
  sans_audio: number
}

/** Un flux candidat renvoyé par l'annuaire, à choisir par l'utilisateur. */
export interface CandidatFlux {
  titre: string
  auteur: string
  feed_url: string
  nb_episodes: number
  vignette: string
  genre: string
}

export interface RechercheFlux {
  /** Ce qui a été envoyé à l'annuaire — affiché pour que la sortie réseau soit lisible. */
  terme: string
  candidats: CandidatFlux[]
  /** Nom de la plateforme si l'URL déjà enregistrée est une page d'écoute, pas un flux. */
  actuel_suspect: string | null
}

/** Une enceinte vue par Home Assistant. `etat` vaut `unavailable` si elle est hors ligne. */
export interface Enceinte { entity_id: string; nom: string; etat: string | null }

export const maisonApi = {
  enceintes: () =>
    apiClient.get<{ enceintes: Enceinte[] }>('/maison/enceintes').then(r => r.data.enceintes),
  diffuser: (entity_id: string, audio_url: string, titre?: string) =>
    apiClient.post<{ diffuse: boolean; enceinte: string }>('/maison/diffuser',
      { entity_id, audio_url, titre }).then(r => r.data),
}

export const dossiersApi = {
  types: () =>
    apiClient.get<{ types: string[]; seeds: SeedDisponible[] }>('/dossiers/types').then(r => r.data),

  list: () =>
    apiClient.get<{ dossiers: DossierResume[] }>('/dossiers').then(r => r.data.dossiers),

  // `ref` accepte l'UUID ou le slug (URLs lisibles : /dossiers/devenir-parent).
  get: (ref: string) =>
    apiClient.get<DossierDetail>(`/dossiers/${ref}`).then(r => r.data),

  // `parent` (UUID ou slug) → crée un SOUS-dossier ; absent → dossier racine.
  create: (data: { titre: string; slug?: string; description?: string; parent?: string }) =>
    apiClient.post<DossierResume>('/dossiers', data).then(r => r.data),

  update: (ref: string, data: Partial<{ titre: string; description: string }>) =>
    apiClient.patch<DossierResume>(`/dossiers/${ref}`, data).then(r => r.data),

  remove: (ref: string) =>
    apiClient.delete<{ message: string }>(`/dossiers/${ref}`).then(r => r.data),

  addRessource: (ref: string, data: RessourceInput) =>
    apiClient.post<Ressource>(`/dossiers/${ref}/ressources`, data).then(r => r.data),

  updateRessource: (id: string, data: Partial<RessourceInput & { position: number }>) =>
    apiClient.patch<Ressource>(`/dossiers/ressources/${id}`, data).then(r => r.data),

  // Résumé IA (IA LOCALE) : propose un court texte, ne l'enregistre pas (l'UI décide).
  resumerRessource: (id: string) =>
    apiClientLong.post<{ resume: string }>(`/dossiers/ressources/${id}/resume`).then(r => r.data),

  removeRessource: (id: string) =>
    apiClient.delete<{ message: string }>(`/dossiers/ressources/${id}`).then(r => r.data),

  // Déplacement d'une ressource vers un autre dossier de la même famille.
  ciblesDeplacement: (ref: string) =>
    apiClient.get<{ cibles: CibleDeplacement[] }>(`/dossiers/${ref}/cibles-deplacement`).then(r => r.data.cibles),
  moveRessource: (id: string, dossier: string) =>
    apiClient.post<Ressource>(`/dossiers/ressources/${id}/deplacer`, { dossier }).then(r => r.data),

  // Import IA : colle une réponse d'IA web → l'IA LOCALE la parse en ressources (aperçu, rien en base).
  parseImport: (texte: string) =>
    apiClientLong.post<{ ressources: RessourceInput[]; nb: number }>('/dossiers/importer/parse', { texte }).then(r => r.data),
  // Ajoute en masse les ressources validées (idempotent par URL/titre).
  importRessources: (ref: string, ressources: RessourceInput[]) =>
    apiClient.post<{ ajoutees: number; completees: number; ignorees: number }>(
      `/dossiers/${ref}/ressources/import`, { ressources }).then(r => r.data),

  // Installe un dossier pré-rempli. Idempotent : relancé, n'ajoute que ce qui manque.
  installerSeed: (cle: string) =>
    apiClient.post<{
      dossier_id: string; slug: string; cree: boolean
      ajoutees: number; ignorees: number; jalons_ajoutes: number
    }>(`/dossiers/seed/${cle}`).then(r => r.data),

  // ── Veille RSS ──────────────────────────────────────────────────────────────
  listFlux: (ref: string) =>
    apiClient.get<{ flux: FluxRss[]; non_lus: number }>(`/dossiers/${ref}/flux`).then(r => r.data),
  addFlux: (ref: string, url: string, titre?: string) =>
    apiClient.post<FluxRss>(`/dossiers/${ref}/flux`, { url, titre }).then(r => r.data),
  removeFlux: (id: string) =>
    apiClient.delete<{ message: string }>(`/dossiers/flux/${id}`).then(r => r.data),
  // ⚠️ Sortie réseau (action explicite) : télécharge tous les flux du dossier.
  refreshVeille: (ref: string) =>
    apiClientLong.post<{ nouveaux: number; flux: { id: string; titre: string | null; url: string; nouveaux: number; etat: string }[] }>(
      `/dossiers/${ref}/veille/refresh`,
    ).then(r => r.data),
  listVeille: (ref: string, nonLus = false) =>
    apiClient.get<{ items: VeilleItem[]; nb: number }>(`/dossiers/${ref}/veille`, { params: { non_lus: nonLus } }).then(r => r.data),
  markItemLu: (id: string, lu = true) =>
    apiClient.post<{ id: string; lu: boolean }>(`/dossiers/veille/${id}/lu`, { lu }).then(r => r.data),
  markAllLu: (ref: string) =>
    apiClient.post<{ marques: number }>(`/dossiers/${ref}/veille/lu-tout`).then(r => r.data),
  removeItem: (id: string) =>
    apiClient.delete<{ message: string }>(`/dossiers/veille/${id}`).then(r => r.data),
  promouvoirItem: (id: string, data: { type?: string; groupe?: string } = {}) =>
    apiClient.post<{ promu: boolean; deja_present: boolean }>(`/dossiers/veille/${id}/promouvoir`, data).then(r => r.data),

  // ── Rétroplanning ──────────────────────────────────────────────────────────
  // `dateTerme` surcharge ponctuellement l'ancre enregistrée dans les Paramètres
  // (utile pour simuler « et si le terme tombait deux semaines plus tôt ? »).
  planning: (ref: string, dateTerme?: string) =>
    apiClient.get<Planning>(`/dossiers/${ref}/planning`, {
      params: dateTerme ? { date_terme: dateTerme } : undefined,
    }).then(r => r.data),

  addJalon: (ref: string, data: JalonInput) =>
    apiClient.post<Jalon>(`/dossiers/${ref}/jalons`, data).then(r => r.data),

  updateJalon: (id: string, data: Partial<JalonInput & { fait: boolean; note_perso: string | null }>) =>
    apiClient.patch<Jalon>(`/dossiers/jalons/${id}`, data).then(r => r.data),

  removeJalon: (id: string) =>
    apiClient.delete<{ message: string }>(`/dossiers/jalons/${id}`).then(r => r.data),

  /**
   * Transforme un texte libre en proposition d'événement — **IA LOCALE, n'écrit rien**.
   * Client à timeout long : un modèle froid met parfois une minute à répondre.
   */
  analyserJalon: (ref: string, texte: string) =>
    apiClientLong.post<{ proposition: PropositionJalon }>(`/dossiers/${ref}/jalons/analyser`,
      { texte }).then(r => r.data.proposition),

  /**
   * URL de l'export iCalendar. On rend une URL et pas un blob : le téléchargement passe par
   * une navigation normale du navigateur, seule voie fiable quand l'application est servie
   * en HTTP (les téléchargements pilotés en JS y sont capricieux).
   */
  /**
   * Épisodes d'un podcast, lus dans son flux. **POST** et non GET : c'est une sortie réseau
   * vers l'éditeur, pas une lecture de notre base — un préchargement ne doit pas la déclencher.
   */
  episodes: (rid: string) =>
    apiClientLong.post<EpisodesPodcast>(`/dossiers/ressources/${rid}/episodes`).then(r => r.data),

  /**
   * Retrouve l'adresse du flux RSS d'un podcast à partir de son nom (annuaire Apple).
   * **POST**, sortie Internet : seuls le titre et l'auteur sortent. N'écrit rien en base.
   */
  chercherFlux: (rid: string) =>
    apiClientLong.post<RechercheFlux>(`/dossiers/ressources/${rid}/chercher-flux`).then(r => r.data),

  planningIcsUrl: (ref: string) => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/dossiers/${ref}/planning.ics`
  },

  /**
   * URL d'export iCalendar d'UN SEUL événement — celui qu'on vient d'ajouter ou de modifier,
   * à importer dans Google/Outlook/Apple sans y déverser tout le rétroplanning. Même `UID`
   * que dans l'export complet : réimporter met à jour, ne duplique pas.
   */
  jalonIcsUrl: (id: string) => {
    const base = import.meta.env.VITE_API_URL ?? ''
    return `${base}/api/dossiers/jalons/${id}.ics`
  },
}

// ─── Aide à la déclaration d'impôts (Administration) ────────────────────────────────
// La synthèse est rangée comme le FORMULAIRE (formulaire → case), pas comme les modules :
// on remplit une déclaration en la descendant. Le module d'origine reste sur la ligne,
// en `provenance`.

export interface SourceFiscale {
  libelle: string
  type: string            // 'document' | 'contrat' | 'fiche' | 'externe'
  ref: string | null      // id interne → lien construit côté front
  url: string | null      // lien externe
  annee: number | null
  // false = année DÉDUITE de la date du fichier (pas de la dépense). L'écran le montre et
  // propose de trancher, plutôt que d'afficher une précision qu'on n'a pas.
  annee_confirmee: boolean
}

export interface CandidatAnnee {
  annee: number
  score: number
  occurrences: number
  extrait: string | null   // le texte qui justifie la proposition — montré tel quel
  motif: string            // « au titre », « nom du fichier », « date »…
}

export interface EtatDatation {
  document_id: string
  nom: string
  annee: number | null
  confirmee: boolean
  annee_deduite: number | null
  origine_deduite: string
  texte_disponible?: boolean
  candidats?: CandidatAnnee[]
}

export interface QuestionFiscale {
  cle: string
  intitule: string
  aide: string | null
  options: { valeur: string; libelle: string }[]
}

export interface LigneFiscale {
  formulaire: string
  case: string | null     // null = une question doit d'abord trancher
  libelle: string
  montant: string | null  // chaîne : un montant destiné à être recopié ne passe pas par un float
  nature: string
  confiance: 'calcule' | 'partiel' | 'a_verifier' | 'a_saisir'
  note: string | null
  notice_url: string | null
  bareme_verifie_le: string | null
  provenance: string
  sources: SourceFiscale[]
  question: QuestionFiscale | null
}

export interface SyntheseFiscale {
  annee: number
  annees_disponibles: number[]
  millesime: { annee: number; verifie_le: string; avertissement: string; url_officielle: string }
  formulaires: { code: string; libelle: string; lignes: LigneFiscale[] }[]
  contributeurs: { cle: string; libelle: string; etat: 'ok' | 'vide' | 'erreur'; nb_lignes: number; message: string | null }[]
  reponses: Record<string, string>
  nb_lignes: number
}

export const fiscaliteApi = {
  synthese: (annee?: number) =>
    apiClient.get<SyntheseFiscale>('/fiscalite/synthese', { params: annee ? { annee } : {} }).then(r => r.data),

  /** Mémorise la réponse qui tranche une case, POUR L'ANNÉE, et rend la synthèse à jour. */
  repondre: (annee: number, cle: string, valeur: string) =>
    apiClient.post<SyntheseFiscale>('/fiscalite/reponses', { annee, cle, valeur }).then(r => r.data),

  disponible: () =>
    apiClient.get<{ disponible: boolean; contributeurs: string[] }>('/fiscalite/disponible').then(r => r.data),

  /**
   * Années candidates pour UNE pièce, la plus probable en tête, chacune avec l'extrait qui
   * la justifie. **Aucune sortie réseau** : la date est dans le texte déjà extrait par Tika.
   */
  datation: (documentId: string) =>
    apiClient.get<EtatDatation>(`/fiscalite/datation/${documentId}`).then(r => r.data),

  /** Fixe l'année de la pièce ; `null` la relâche (retour à la date du fichier). */
  dater: (documentId: string, annee: number | null) =>
    apiClient.post<EtatDatation>(`/fiscalite/datation/${documentId}`, { annee }).then(r => r.data),
}


// ─── Module emploi à domicile (onglet « Nounou » d'un dossier) ──────────────────────
// Le PROFIL porte le guichet (Pajemploi ou CESU), l'aide et le libellé de l'onglet :
// c'est le LIEU qui décide, pas le métier. Phase 1 = lecture seule.

export interface ProfilEmploi {
  cle: string
  onglet: string          // libellé de l'onglet — « Nounou », « Aide à domicile »…
  libelle: string
  lieu: string
  guichet: string
  aide: string
  socle: string
  resume: string
  documente: boolean
}

/** Un bloc de fiche. Le front rend n'importe quel bloc sans connaître son sujet. */
export interface BlocFiche {
  type: 'texte' | 'vis_a_vis' | 'tableau' | 'points'
  titre: string
  paragraphes?: string[]
  gauche?: string
  droite?: string
  lignes?: ({ sujet: string; employeur: string; salarie: string })[] | string[][]
  entetes?: string[]
  note?: string | null
  items?: { titre: string; detail: string }[]
  ton?: string
}

export interface Fiche {
  cle: string
  titre: string
  chapeau: string
  blocs: BlocFiche[]
}

export interface GroupeChecklist {
  titre: string
  // `cle` est STABLE et sert d'index aux réponses d'un entretien : ne jamais la dériver du
  // texte côté front, une reformulation perdrait les réponses déjà saisies.
  questions: { cle: string; texte: string; pourquoi: string }[]
}

export interface ContenuEmploiDomicile {
  profil: ProfilEmploi
  verifie_le: string
  avertissement: string
  avertissements: string[]
  fiches: Fiche[]
  checklist: GroupeChecklist[]
  // Sources livrées avec le module + liens pertinents repris d'Administration → liens
  // (dédoublonnés par URL) : la liste s'incrémente sans saisie en double.
  liens: { libelle: string; url: string; section?: string | null; origine: 'module' | 'administration' }[]
}

export const emploiDomicileApi = {
  profils: () =>
    apiClient.get<{ profils: ProfilEmploi[] }>('/emploi-domicile/profils').then(r => r.data),

  /** Tout l'onglet en un appel : l'écran n'a rien à recomposer. */
  fiches: (profil?: string) =>
    apiClient.get<ContenuEmploiDomicile>('/emploi-domicile/fiches',
      { params: profil ? { profil } : {} }).then(r => r.data),
}


// ─── Visites : intervenants et entretiens ───────────────────────────────────────────
// La checklist appartient à l'ENTRETIEN, pas à la personne : une seconde visite a ses
// propres réponses, et c'est l'écart entre les deux qui informe.

export type AvisReponse = 'ok' | 'reserve' | 'non'

export interface Entretien {
  id: string
  intervenant_id: string
  rang: number                    // 1ᵉʳ, 2ᵉ… — sert à nommer et à proposer la reprise
  type: string                    // 'telephone' | 'visite' | 'seconde_visite' | 'suivi'
  statut: string                  // 'planifie' | 'fait' | 'annule'
  date_prevue: string | null
  heure_debut: string | null
  heure_fin: string | null
  lieu: string | null
  impression: number | null       // 1 à 5, saisie APRÈS la visite
  note: string | null
  reponses: Record<string, { avis: AvisReponse | null; texte: string | null }>
  nb_repondues: number
  jalon_id: string | null
  created_at: string | null
}

export interface Intervenant {
  id: string
  dossier_id: string
  profil: string
  nom: string
  prenom: string | null
  telephone: string | null
  email: string | null
  commune: string | null
  adresse: string | null
  agrement_numero: string | null
  agrement_echeance: string | null
  agrement_perime: boolean        // sans agrément valide : ni aide, ni accueil légal
  places: number | null
  tarif_annonce: string | null
  disponibilite: string | null
  statut: string
  note: string | null
  nb_entretiens: number
  prochain_rdv: Entretien | null
  created_at: string | null
}

export interface IntervenantDetail extends Intervenant {
  entretiens: Entretien[]
}

export type IntervenantInput = Partial<Omit<Intervenant,
  'id' | 'dossier_id' | 'agrement_perime' | 'nb_entretiens' | 'prochain_rdv' | 'created_at'>>
  & { nom: string }

export interface EntretienInput {
  type?: string
  date_prevue?: string | null
  heure_debut?: string | null
  heure_fin?: string | null
  lieu?: string | null
  note?: string | null
  /** 'precedent' = reprendre les réponses du dernier entretien, ou son id. */
  reprendre_de?: string
}

export const visitesApi = {
  lister: (ref: string) =>
    apiClient.get<{ dossier: { id: string; slug: string; titre: string }
      intervenants: Intervenant[]; statuts: string[]; types_entretien: string[] }>(
      `/emploi-domicile/${ref}/intervenants`).then(r => r.data),

  creer: (ref: string, body: IntervenantInput) =>
    apiClient.post<Intervenant>(`/emploi-domicile/${ref}/intervenants`, body).then(r => r.data),

  detail: (id: string) =>
    apiClient.get<IntervenantDetail>(`/emploi-domicile/intervenants/${id}`).then(r => r.data),

  modifier: (id: string, body: Partial<IntervenantInput>) =>
    apiClient.patch<Intervenant>(`/emploi-domicile/intervenants/${id}`, body).then(r => r.data),

  supprimer: (id: string) =>
    apiClient.delete(`/emploi-domicile/intervenants/${id}`).then(r => r.data),

  creerEntretien: (intervenantId: string, body: EntretienInput) =>
    apiClient.post<Entretien>(`/emploi-domicile/intervenants/${intervenantId}/entretiens`, body)
      .then(r => r.data),

  modifierEntretien: (id: string, body: Partial<EntretienInput> & { statut?: string; impression?: number | null }) =>
    apiClient.patch<Entretien>(`/emploi-domicile/entretiens/${id}`, body).then(r => r.data),

  /** UNE réponse à la fois : la fiche se remplit debout, au bout d'un VPN. */
  repondre: (entretienId: string, cle: string, avis: AvisReponse | null, texte: string | null) =>
    apiClient.post<Entretien>(`/emploi-domicile/entretiens/${entretienId}/reponse`,
      { cle, avis, texte }).then(r => r.data),

  supprimerEntretien: (id: string) =>
    apiClient.delete(`/emploi-domicile/entretiens/${id}`).then(r => r.data),
}
