# ROADMAP — Matothèque

> GED locale intelligente (extraction Tika + IA Ollama + recherche sémantique
> pgvector), 100 % locale. Repo `AgestiTC/ged-local` · cible **NAS-MATO**
> (Synology, 192.168.42.200) · version courante **1.7.2**.

## Statut général

🟢 **Projet avancé** — socle technique complet et fonctionnel (extraction,
indexation, recherche hybride, GED, rapports, comparatif). La suite consiste à
**brancher sur le NAS** et à couvrir 3 besoins métier prioritaires.

---

## ✅ Acquis (déjà livré, ≤ v1.7.2)

- [x] Pipeline extraction tous formats (Tika) + enrichissement IA (Ollama)
- [x] Indexation de **dossiers surveillés** (`/api/folders`, scan, browse) + workflow n8n `folder-watcher`
- [x] **Recherche hybride** full-text (pg_trgm/tsvector) + sémantique (pondération 40/60)
- [x] Détection de **doublons exacts** (SHA256) à l'ingestion + `POST /documents/purge-duplicates`
- [x] GED : catégories, tags, résumés IA · filtres par catégorie
- [x] Rapports libres + remplissage de templates + **rapport comparatif multi-groupes**
- [x] Alignement modèle AgestiTC : VERSION, `/api/version` `/healthz` `/api/logs/tail`,
      Dockerfile non-root, CI build+verify, Dependabot, audit hebdo, hooks `.claude`

### Livré sur `develop` depuis 1.7.2 (non encore taggé)

- [x] **Docker de dev complet** « tout en conteneurs » (pattern NetSight) :
      `Dockerfile.dev` backend+frontend, `docker-compose.dev.yml` autonome, HMR, coexiste avec NetSight
- [x] **Doublons** : page dédiée + quarantaine `DOUBLON-MATOTEQUE` (cf. Phase 2)
- [x] **Paramètres — Services & modèles IA** : URLs Tika/Ollama/n8n **configurables en base**
      (éditables à chaud) + test connexion + statut live ; **liste des modèles dynamique**
      depuis Ollama + bouton rafraîchir (fin du hard-code)

---

## 🎯 Besoins prioritaires (le « pourquoi » du projet)

### Phase 1 — Retrouver facilement les fichiers du NAS (v1.8.x)
*Besoin n°1. Le moteur existe ; il faut le brancher sur le vrai volume NAS-MATO et fiabiliser l'usage quotidien.*

- [ ] **🔁 Refonte « Dossiers surveillés » → Sources SMB configurables** (décidé) :
      remplacer la saisie manuelle d'un chemin `/app/documents` (+ encart « montez le NAS
      dans docker-compose ») par : choisir un **serveur** (défaut NAS-MATO 192.168.42.200),
      **lister ses partages via SMB**, cocher les dossiers à indexer. Source générique
      `{type, hôte, chemin, identifiants}` en base → ajouter un autre serveur sans toucher au compose.
- [ ] Configurer le(s) **dossier(s) surveillé(s)** pointant vers le partage NAS-MATO (montage lecture seule)
- [ ] Activer le **watcher n8n en continu** (détection nouveaux/modifiés) + cron de réindexation
- [ ] **Première indexation complète** du volume + suivi de progression
- [ ] Valider la **recherche hybride** sur le vrai corpus (pertinence, vitesse) ; ajuster la pondération si besoin
- [ ] Barre de recherche : aperçu du document + **chemin NAS** + bouton « ouvrir l'emplacement »

### Phase 2 — Identifier et gérer les doublons (v1.9.x) — 🟢 en grande partie livré
*Besoin n°2. Détection disque + déplacement vers DOUBLON-MATOTEQUE (pas de suppression).*

- [x] **Scan disque des doublons** (groupe par taille → SHA256), endpoint `GET /api/duplicates`
- [x] **Écran « Doublons »** : groupes + **case à cocher** par fichier (pré-cochées sauf le « à garder »)
- [x] **Déplacement** (`POST /api/duplicates/quarantine`) vers `DOUBLON-MATOTEQUE/` + **modal de confirmation**
- [x] Garde-fous : jamais de suppression (déplacement réversible), anti path-traversal, exclu de l'indexation
- [ ] **Quasi-doublons** : détection par similarité sémantique des embeddings (seuil réglable)
- [ ] Bouton « ouvrir l'emplacement » + aperçu du fichier dans chaque ligne
- [ ] **Miniatures / aperçu** des fichiers en double pour faciliter la comparaison visuelle
- [ ] **Photos** : détection des images **floues** (ex. variance du Laplacien) → proposer
      de garder la plus nette et éliminer les floues

### Phase 3 — Grouper / parcourir les documents (v1.10.x)
*Besoin n°3 : grouper par extension, thème/catégorie, …*

- [ ] **Vue groupée** de la GED : regroupement par **extension** (PDF, DOCX, XLSX…)
- [ ] Regroupement par **thème / catégorie IA** et par **tags**
- [ ] Regroupement par **dossier source** NAS
- [ ] Facettes combinables (extension × thème × date) + compteurs par groupe

---

### Administration des modèles IA — 🟢 livré
*Gérer les modèles Ollama directement depuis Matothèque (Paramètres).*

- [x] **⚠️ Détection des mises à jour** : digest local vs manifest registre Ollama →
      badge ⚠️ « MAJ », ✓ à jour, ? custom hors registre (`GET /api/system/models?check_updates`)
- [x] **Bouton mettre à jour** un modèle (`ollama pull`) avec progression en streaming
      (`POST /api/system/models/pull`)
- [ ] (option) supprimer / télécharger un **nouveau** modèle depuis l'UI

---

### Réorganisation d'arborescence par IA (plan validé — à coder)
*Ranger automatiquement les documents dans une meilleure arborescence, avec l'IA.*

**Décisions actées :**
- **Virtuel → physique** : on conçoit l'arbo en **virtuel** (aperçu, sans toucher au NAS),
  puis un bouton **« Appliquer au NAS »** déplace réellement les fichiers.
- **Hybride** : l'**IA propose** une arborescence + ses critères → l'utilisateur **ajuste
  en drag & drop** → valide.
- **Critères définis avec l'IA** (pas figés) : l'IA suggère le rangement selon le corpus
  (catégorie, entités/clients, dates, thèmes) ; l'utilisateur peut la réorienter
  (« plutôt par client », « par année »…).

**Flux cible :**
1. Choisir un périmètre (une source / un dossier / tout l'index).
2. **IA propose** : à partir des métadonnées déjà extraites (catégorie, sous-catégorie,
   tags, entités, dates), le LLM renvoie une **arbo cible** + le mapping `doc → chemin cible`
   + une explication des critères.
3. **Aperçu (virtuel)** : arbre éditable en **drag & drop** (déplacer/renommer dossiers),
   bouton « re-proposer avec une consigne ».
4. **Appliquer** :
   - **Vue virtuelle** : enregistre l'organisation comme **arborescence logique** dans
     Matothèque (navigation GED), **sans déplacer** les fichiers.
   - **Au NAS (physique)** : **déplace** réellement les fichiers (local + SMB) après
     confirmation, avec **journal d'annulation** (undo).

**Garde-fous (mode physique)** : aperçu/dry-run obligatoire · **déplacer, jamais supprimer** ·
gestion des collisions · anti path-traversal · exclut `DOUBLON-MATOTEQUE` · **log undo**
(mapping origine→destination) pour revenir en arrière · volume RW requis.

**Briques réutilisées :** classification IA existante · déplacement fichiers (doublons) ·
sources local/SMB.

**À cadrer au démarrage du code :** représentation de la vue virtuelle (table
`arborescence_logique` vs tags) · format du plan (table `reorganisations`) · stratégie undo.

- [ ] Backend : `POST /api/organize/propose` (LLM → arbo + mapping)
- [ ] Backend : persistance du plan (éditable) + `POST /api/organize/apply` (virtuel | physique + undo)
- [ ] Frontend : page « Réorganiser » — périmètre → proposer (IA) → arbre drag & drop → appliquer
- [ ] Garde-fous physiques + journal d'annulation

---

## 🚀 Phase 4 — Mise en production sur NAS-MATO (v2.0.0)

- [ ] Release CI (`scripts/release.ps1`) → images GHCR `docflow-backend` / `docflow-frontend`
- [ ] Déploiement Container Manager (Synology) — cf. [docs/synology-deployment.md](docs/synology-deployment.md)
- [ ] `.env.nas` validé (volumes NAS, Ollama hôte) + smoke test `scripts/validate.ps1`
- [ ] Plan de sauvegarde (bind-mounts `./bdd-` / `./data-`) validé

---

## 📝 Backlog — idées à cadrer (besoins 4+)

Pistes retenues, à prioriser/chiffrer avant d'en faire des phases :

- [ ] **Renommage automatique** des fichiers selon une convention (date, thème, entités IA détectées) — proposition + validation, jamais en écrasant l'original sans confirmation
- [ ] **OCR des scans** : fallback `glm-ocr`/Tesseract quand Tika ne sort pas de texte (PDF images, photos de documents)
- [ ] **Partage & permissions** : auth + rôles (utilisateur / admin / super-admin, cf. modèle), accès par dossier/catégorie, liens de partage internes
- [ ] **Alertes / notifications** : nouveau document, doublon détecté, échec d'indexation (mail + webhook n8n/Discord, cf. modèle)

---

## Changelog versionné

Le détail des versions est tenu dans [CHANGELOG.md](CHANGELOG.md).
Chaque release passe par `scripts/release.ps1 -Version X.Y.Z -Message "…"`
(bump `VERSION` + tag `vX.Y.Z` → CI build + verify → images GHCR).
