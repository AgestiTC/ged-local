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

## Logique de tri reprise d'`ant-tool` (prototype de référence)

`ant-tool` (`git.agesti.fr/tclement/ant-tool`, PowerShell + HTML) est le **prototype
historique** de cette fonctionnalité (`ANT_AppSorter_Sort.ps1`). On reprend sa logique
éprouvée — sans son code (stack incompatible) :

- **Chemin cible** : `destination / {catégorie} / {fichier}` (la catégorie = dossier de
  rangement). Notre version : la catégorie/critère vient de l'IA (hybride, ajustable).
- **Move ou Copy** : option « déplacer » (range vraiment) vs « copier » (laisse l'original).
  MVP Matothèque : **déplacer** (au NAS), avec undo.
- **Corbeille réversible** : ant-tool déplace vers `_Doublons_Corbeille` avant toute
  suppression définitive → exactement notre pattern `DOUBLON-MATOTEQUE`. **Jamais de
  suppression sèche.**
- **Collisions de noms** : suffixe `_(n)` si le fichier existe déjà à destination.
- **Confirmation explicite** obligatoire avant tout déplacement (règle ant-tool reprise).

### Taxonomie de catégories par défaut (d'`ant-tool`, à proposer/ajuster par l'IA)

Images · Audio · Vidéo · Bureautique · Applications · Archives · Code source · Polices ·
Modèles 3D · Disques virtuels · Inconnu. *(Pour une GED documentaire, l'IA affinera plutôt
par thème métier : Factures, Contrats, RH, Compta… — la taxonomie ant-tool sert de filet
pour les fichiers non-documentaires.)*

### Optimisation dédup à porter (bonus, hors reorg)

ant-tool hashe les doublons en **3 passes** : taille → **hash partiel (4 Ko)** → hash
complet. Notre scan doublons fait taille → hash complet ; ajouter la passe intermédiaire
accélère sur gros fichiers réseau (NAS). → à ajouter à la Phase 2 (doublons).

## Tâches

- [ ] Backend : `POST /api/organize/propose` (LLM → arbo + mapping + critères)
- [ ] Backend : persistance du plan (éditable) + `POST /api/organize/apply` (virtuel | physique + undo)
- [ ] Backend : `POST /api/organize/undo` (rollback d'une application physique)
- [ ] Frontend : page « Réorganiser » — périmètre → proposer (IA) → arbre drag & drop → appliquer
- [ ] Garde-fous physiques + journal d'annulation
