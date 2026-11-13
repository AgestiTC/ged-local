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

// ── Plan de classement (étape 9) — docs/conception-plan-classement.md ──────────
export interface PlanNoeud {
  id: number
  partage: string
  parent_id: number | null
  nom: string
  chemin: string
  gabarit: string | null
  verrouille: boolean
  origine: string
  description: string | null
}

export interface PlanRegle {
  id: number
  priorite: number
  type: 'famille' | 'extension' | 'motif_nom' | 'motif_chemin' | string
  valeur: string
  noeud_id: number
  active: boolean
  origine: string
  description: string | null
  valide_par: string | null
  valide_le: string | null
}

export type StatutProposition = 'proposee' | 'validee' | 'refusee' | 'en_place' | 'sans_place'

export interface PlanProposition {
  id: number
  emplacement_id: number
  chemin: string
  est_dossier: boolean
  taille: number
  destination: string | null
  noeud_id: number | null
  regle_id: number | null
  par: 'regle' | 'ia' | 'humain' | null
  raison: string | null
  confiance: number | null
  statut: StatutProposition
  valide_par: string | null
  valide_le: string | null
  calcule_le: string | null
}

export const planApi = {
  lire: (partage?: string) =>
    apiClient.get<{ noeuds: PlanNoeud[]; regles: PlanRegle[]; types_regle: string[] }>(
      '/inventaire/plan', { params: partage ? { partage } : {} }).then(r => r.data),
  chargerModele: (emplacementId: number) =>
    apiClient.post<{ partage: string; noeuds_crees: number; regles_creees: number }>(
      `/inventaire/plan/modele/${emplacementId}`).then(r => r.data),
  creerNoeud: (partage: string, nom: string, parent_id: number | null, description?: string) =>
    apiClient.post<PlanNoeud>('/inventaire/plan/noeuds', { partage, nom, parent_id, description }).then(r => r.data),
  modifierNoeud: (id: number, changements: { nom?: string; description?: string; gabarit?: string }) =>
    apiClient.patch<PlanNoeud>(`/inventaire/plan/noeuds/${id}`, changements).then(r => r.data),
  supprimerNoeud: (id: number) => apiClient.delete(`/inventaire/plan/noeuds/${id}`).then(r => r.data),
  creerRegle: (regle: { type: string; valeur: string; noeud_id: number; priorite: number; description?: string }) =>
    apiClient.post<PlanRegle>('/inventaire/plan/regles', regle).then(r => r.data),
  modifierRegle: (id: number, changements: { active?: boolean; priorite?: number }) =>
    apiClient.patch<PlanRegle>(`/inventaire/plan/regles/${id}`, changements).then(r => r.data),
  supprimerRegle: (id: number) => apiClient.delete(`/inventaire/plan/regles/${id}`).then(r => r.data),
  calculer: (emplacementId: number, ia: boolean) =>
    apiClient.post<Lancement>(`/inventaire/plan/calcul/${emplacementId}`, null, { params: { ia } }).then(r => r.data),
  propositions: (emplacementId: number) =>
    apiClient.get<{ propositions: PlanProposition[]; compte: Record<string, number> }>(
      '/inventaire/plan/propositions', { params: { emplacement_id: emplacementId } }).then(r => r.data),
  decider: (id: number, statut: 'validee' | 'refusee', destination?: string) =>
    apiClient.post<PlanProposition>(`/inventaire/plan/propositions/${id}/decision`, { statut, destination }).then(r => r.data),
  validerParRegle: (regleId: number, emplacementId: number) =>
    apiClient.post<{ validees: number }>(`/inventaire/plan/regles/${regleId}/valider-propositions`, null,
      { params: { emplacement_id: emplacementId } }).then(r => r.data),
}
