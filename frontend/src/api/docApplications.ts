/**
 * API — Doc des applications (plan docs/plan-reception-doc-applications.md)
 *  - règles de classement par emplacement (admin) ;
 *  - page « Documentation des applications » (utilisateur) ;
 *  - texte d'une version remplacée.
 */
import { apiClient } from './client'

export type Classement = 'fixe' | 'ia'

export interface RegleClassement {
  id: string
  libelle: string
  prefixe_chemin: string
  categorie: string | null
  sous_categorie: string | null
  tags: string[]
  tag_depuis_sous_dossier: boolean
  classement: Classement
  actif: boolean
}
export type RegleClassementIn = Omit<RegleClassement, 'id'>

export interface DocAppli {
  id: string
  nom: string
  titre: string
  version: string | null
  date_depot: string | null
  nb_versions: number
  statut: string
}
export interface Application {
  appli: string
  regle: string
  documents: DocAppli[]
  dernier_depot: string | null
  en_retard: boolean
}

export interface VersionDoc {
  id: string
  numero_version: number
  date_detection: string | null
  diff_resume: string | null
  libelle: string | null
  archive_disponible: boolean
}

export const reglesClassementApi = {
  lister: () => apiClient.get<{ regles: RegleClassement[] }>('/regles-classement').then(r => r.data.regles),
  creer: (r: RegleClassementIn) => apiClient.post<RegleClassement>('/regles-classement', r).then(x => x.data),
  modifier: (id: string, r: RegleClassementIn) =>
    apiClient.put<RegleClassement>(`/regles-classement/${id}`, r).then(x => x.data),
  supprimer: (id: string) => apiClient.delete(`/regles-classement/${id}`),
}

export const docApplicationsApi = {
  lister: () => apiClient.get<{ applications: Application[]; jours_sans_depot: number }>('/doc-applications')
    .then(r => r.data),
  versions: (documentId: string) =>
    apiClient.get<{ versions: VersionDoc[] }>(`/documents/${documentId}/versions`).then(r => r.data.versions),
  contenuVersion: (documentId: string, versionId: string) =>
    apiClient.get<{ numero_version: number; libelle: string | null; texte: string }>(
      `/documents/${documentId}/versions/${versionId}/contenu`).then(r => r.data),
}
