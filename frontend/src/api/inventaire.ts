/**
 * API de l'inventaire (module Rangement) — `/api/inventaire/*`, administrateur seulement.
 * Contrats : `backend/routers/inventaire.py`. Les scans et imports sont des tâches du worker :
 * les routes qui les lancent répondent 202 avec l'identifiant de la tâche (suivie dans « Tâches »).
 */
import { apiClient } from './client'

export interface ScanInventaire {
  id: number
  statut: 'en_cours' | 'termine' | 'echec' | 'interrompu' | string
  declencheur: string
  nb_dossiers: number
  nb_fichiers: number
  volume_octets: number
  nb_ajouts: number
  nb_modifs: number
  nb_disparus: number
  nb_erreurs: number
  message: string | null
  debut: string | null
  fin: string | null
}

export interface EmplacementInventaire {
  id: number
  libelle: string
  racine: string
  actif: boolean
  source: 'serveur' | 'agent' | 'import' | string
  poste_id: number | null
  dernier_scan: ScanInventaire | null
}

export interface LigneCarte {
  nom: string
  chemin: string
  est_dossier: boolean
  taille: number | null
  pourcent: number
  nb_fichiers: number | null
  variation: number | null
}

export interface VueCarte {
  emplacement: { id: number; libelle: string; racine: string; source: string }
  chemin: string
  fil: { libelle: string; chemin: string }[]
  taille: number | null
  nb_fichiers: number | null
  nb_dossiers: number | null
  lignes: LigneCarte[]
  reste: number
  types: { famille: string; nb: number; octets: number; pourcent: number }[]
  gros: { chemin: string; taille: number }[]
  croissances: { chemin: string; variation: number }[]
  dernier_scan: ScanInventaire | null
  maintenant: string | null
}

export interface PosteInventaire {
  id: number
  nom: string
  actif: boolean
  version: string
  dernier_contact: string | null
  jeton: boolean
  lecture_jour: string | null
  lecture_octets: number
  emplacements: { id: number; libelle: string; racine: string; source: string; actif: boolean }[]
}

export interface Lancement { job_id: string; statut: string }

export const inventaireApi = {
  etat: () => apiClient.get<{ base: string; emplacements: EmplacementInventaire[] }>('/inventaire/etat').then(r => r.data),
  carte: (emplacementId: number, chemin = '') =>
    apiClient.get<VueCarte>(`/inventaire/emplacements/${emplacementId}/carte`, { params: { chemin } }).then(r => r.data),
  declarer: (libelle: string, racine: string) =>
    apiClient.post<{ id: number; libelle: string; racine: string; rescans: number[] }>(
      '/inventaire/emplacements', { libelle, racine }).then(r => r.data),
  activer: (emplacementId: number, actif: boolean) =>
    apiClient.patch(`/inventaire/emplacements/${emplacementId}`, { actif }).then(r => r.data),
  scanner: (emplacementId: number) =>
    apiClient.post<Lancement & { scan_id: number }>(`/inventaire/emplacements/${emplacementId}/scan`).then(r => r.data),

  postes: () => apiClient.get<{ postes: PosteInventaire[] }>('/inventaire/postes').then(r => r.data.postes),
  creerPoste: (nom: string) =>
    apiClient.post<PosteInventaire & { jeton_clair: string }>('/inventaire/postes', { nom }).then(r => r.data),
  nouveauJeton: (posteId: number) =>
    apiClient.post<{ id: number; jeton_clair: string }>(`/inventaire/postes/${posteId}/jeton`).then(r => r.data),
  activerPoste: (posteId: number, actif: boolean) =>
    apiClient.patch(`/inventaire/postes/${posteId}`, { actif }).then(r => r.data),
  confierDossier: (posteId: number, libelle: string, racine: string) =>
    apiClient.post(`/inventaire/postes/${posteId}/emplacements`, { libelle, racine }).then(r => r.data),
  importerWizTree: (nom_pc: string, libelle: string, chemin: string) =>
    apiClient.post<Lancement>('/inventaire/imports', { nom_pc, libelle, chemin }).then(r => r.data),
}
