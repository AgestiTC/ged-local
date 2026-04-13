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
}

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

  getMetadata: (id: string) =>
    apiClient.get<MetadonneeIA>(`/documents/${id}/metadata`).then(r => r.data),

  patchMetadata: (id: string, data: Partial<Pick<MetadonneeIA, 'tags' | 'categorie' | 'sous_categorie' | 'resume' | 'niveau_confidentialite' | 'mots_cles'>>) =>
    apiClient.patch<MetadonneeIA>(`/documents/${id}/metadata`, data).then(r => r.data),

  getVersions: (id: string) =>
    apiClient.get<{ document_id: string; versions: DocumentVersion[] }>(`/documents/${id}/versions`).then(r => r.data),

  delete: (id: string) =>
    apiClient.delete(`/documents/${id}`).then(r => r.data),
}

// ─── Upload ──────────────────────────────────────────────────────────────────

export interface UploadResponse {
  jobs: Array<{ fichier: string; job_id?: string; statut: string; raison?: string }>
}

export const uploadApi = {
  uploadFiles: (files: File[], onProgress?: (pct: number) => void) => {
    const form = new FormData()
    files.forEach(f => form.append('files', f))
    return apiClient.post<UploadResponse>('/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
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

  /** Retourne l'URL SSE pour EventSource */
  getStreamUrl: (jobId: string) =>
    `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/generate/stream/${jobId}`,
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

export const systemApi = {
  health: () =>
    apiClient.get<{
      status: string
      version: string
      services: { tika: { url: string; disponible: boolean }; ollama: { url: string; disponible: boolean } }
    }>('/health', { baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000' }).then(r => r.data),

  listModels: () =>
    apiClient.get<{ models: Array<{ name: string }> }>(
      '/api/tags',
      { baseURL: import.meta.env.VITE_OLLAMA_URL || 'http://localhost:11434' }
    ).then(r => r.data.models.map(m => m.name)).catch(() => [] as string[]),
}
