/**
 * Types TypeScript partagés — DocFlow AI
 * ========================================
 * Ces types correspondent au schéma DB et aux réponses API.
 */

// --- Documents ---

export type DocumentStatut = 'pending' | 'extracted' | 'enriched' | 'error'
export type DocumentSource = 'watch' | 'upload' | 'drag_drop'

export interface Document {
  id: string
  chemin: string
  nom: string
  extension: string
  type_mime?: string
  hash_sha256: string
  taille_octets?: number
  date_import: string
  date_modification_fichier?: string
  statut: DocumentStatut
  source: DocumentSource
  metadonnees_ia?: MetadonneeIA
  erreur?: string
}

export interface DocumentVersion {
  id: string
  numero_version: number
  hash_sha256: string
  taille_octets?: number
  date_detection: string
  diff_resume?: string
}

export interface MetadonneeIA {
  id: string
  document_id: string
  categorie?: string
  sous_categorie?: string
  tags?: string[]
  resume?: string
  langue?: string
  entites?: {
    personnes: string[]
    dates: string[]
    lieux: string[]
    organisations: string[]
  }
  mots_cles?: string[]
  niveau_confidentialite: 'normal' | 'confidentiel' | 'restreint'
  modele_utilise?: string
}

// --- Jobs ---

export type JobType = 'extraction' | 'enrichissement' | 'rapport' | 'embedding'
export type JobStatut = 'pending' | 'running' | 'completed' | 'failed'

export interface Job {
  id: string
  type: JobType
  statut: JobStatut
  document_id?: string
  erreur?: string
  created_at: string
  started_at?: string
  completed_at?: string
}

// --- Rapports ---

export type OutputMode = 'rapport_libre' | 'remplir_template' | 'classement' | 'comparatif'

export interface GroupeComparatif {
  id: string           // identifiant local React uniquement
  nom: string
  document_ids: string[]
}

export interface CompareRequest {
  groupes: { nom: string; document_ids: string[] }[]
  template_id: string
  model?: string
  instructions?: string
}

export type CompareStatut = 'pending' | 'running' | 'done' | 'error'

export interface CompareEvent {
  groupe?: string
  statut: 'running' | 'done' | 'complete' | 'failed'
  index?: number
  total?: number
  download_url?: string
  erreur?: string
}

export interface GenerateReportRequest {
  document_ids: string[]
  prompt: string
  model?: string
  output_format?: 'markdown' | 'text'
}

export interface FillTemplateRequest {
  document_ids: string[]
  template_id: string
  instructions?: string
  model?: string
}

// --- Templates ---

export interface Template {
  id: string
  nom: string
  description?: string
  type: 'docx' | 'pdf'
  champs?: TemplateField[]
  created_at: string
}

export interface TemplateField {
  nom: string
  type: string
  description?: string
}

// --- Prompts ---

export interface PromptPreset {
  id: string
  nom: string
  description?: string
  prompt_text: string
  categorie?: 'rapport' | 'classement' | 'extraction' | 'analyse'
  modele_prefere?: string
}

// --- Recherche ---

export type SearchType = 'hybrid' | 'text' | 'semantic'

export interface SearchResult {
  document: Document
  score: number
  extrait?: string  // Extrait du texte avec highlight
}

export interface SearchFilters {
  categorie?: string
  tags?: string[]
  extension?: string
  date_debut?: string
  date_fin?: string
}

// --- Dossiers surveillés ---

export interface DossierSurveille {
  id: string
  chemin: string
  nom_affichage?: string
  actif: boolean
  recursive: boolean
  extensions_filtrees?: string[]
  intervalle_scan_secondes: number
  dernier_scan?: string
}

// --- API Responses ---

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  per_page: number
}

export interface ApiError {
  detail: string
  code?: string
}
