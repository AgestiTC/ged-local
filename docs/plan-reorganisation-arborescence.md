# Plan — Réorganisation d'arborescence par IA

> Plan de conception (validé avec l'utilisateur, **à coder**). Référencé depuis
> [ROADMAP.md](../ROADMAP.md). But : ranger automatiquement les documents dans une
> meilleure arborescence, avec l'IA, sans risque.

## Objectif

Permettre à Matothèque de **proposer puis appliquer** une réorganisation des
documents en dossiers, en s'appuyant sur la classification IA déjà existante
(catégorie, sous-catégorie, tags, entités, dates, résumé).

## Décisions actées

- **Virtuel → physique** : on conçoit l'arborescence en **virtuel** (aperçu, sans
  toucher au NAS), puis un bouton **« Appliquer au NAS »** déplace réellement les fichiers.
- **Hybride** : l'**IA propose** une arborescence + ses critères → l'utilisateur
  **ajuste en drag & drop** → valide.
- **Critères définis avec l'IA** (pas figés) : l'IA suggère le rangement selon le
  corpus ; l'utilisateur peut la réorienter (« plutôt par client », « par année »…).

## Flux cible

1. **Périmètre** : choisir une source / un dossier / tout l'index.
2. **Proposition IA** : à partir des métadonnées extraites, le LLM renvoie une
   **arbo cible** + le mapping `doc → chemin cible` + une explication des critères.
3. **Aperçu (virtuel)** : arbre **éditable en drag & drop** (déplacer / renommer
   dossiers), bouton « re-proposer avec une consigne ».
4. **Appliquer** :
   - **Vue virtuelle** : enregistre l'organisation comme **arborescence logique**
     (navigation GED), **sans déplacer** les fichiers.
   - **Au NAS (physique)** : **déplace** réellement les fichiers (local + SMB) après
     confirmation, avec **journal d'annulation** (undo).

## Garde-fous (mode physique)

Aperçu / dry-run obligatoire · **déplacer, jamais supprimer** · gestion des collisions ·
anti path-traversal · exclut `DOUBLON-MATOTEQUE` · **log undo** (mapping origine→destination)
pour revenir en arrière · volume RW requis.

## Briques réutilisées

- Classification IA existante (catégorie, tags, entités, dates).
- Déplacement de fichiers avec garde-fous (déjà fait pour les **doublons**).
- Sources **local / SMB** (déjà en place).

## À cadrer au démarrage du code

- Représentation de la **vue virtuelle** : table `arborescence_logique` vs tags.
- Format du **plan** de réorganisation : table `reorganisations` (éditable).
- Stratégie **undo** : log origine→destination + endpoint de rollback.

## Tâches

- [ ] Backend : `POST /api/organize/propose` (LLM → arbo + mapping + critères)
- [ ] Backend : persistance du plan (éditable) + `POST /api/organize/apply` (virtuel | physique + undo)
- [ ] Backend : `POST /api/organize/undo` (rollback d'une application physique)
- [ ] Frontend : page « Réorganiser » — périmètre → proposer (IA) → arbre drag & drop → appliquer
- [ ] Garde-fous physiques + journal d'annulation
