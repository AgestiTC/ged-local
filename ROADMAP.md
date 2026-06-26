# ROADMAP — Matothèque

> GED locale intelligente (extraction Tika + IA Ollama + recherche sémantique
> pgvector), 100 % locale. Repo `AgestiTC/ged-local` · cible **NAS-MATO**
> (Synology, 192.168.42.200) · version courante **1.7.2**.

## Statut général

🟢 **Projet avancé** — socle technique complet et fonctionnel (extraction,
indexation, recherche hybride, GED, rapports, comparatif). La suite consiste à
**brancher sur le NAS** et à couvrir les besoins métier prioritaires.

> **Légende des états** : `[ ]` à faire · `[~]` en cours · `[x]` fait.

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
- [x] **Administration des modèles IA** : détection MAJ (⚠️ digest vs registre) + mise à jour
      (`ollama pull` en streaming) depuis l'UI
- [x] **Sources de fichiers (local + SMB NAS)** : déclarer un serveur, lister ses partages SMB,
      parcourir avec **cases à cocher** (tout cocher/décocher), **indexer la sélection** ;
      identifiants **chiffrés (Fernet)** en base. ✅ validé sur le vrai NAS-MATO.
- [x] **Antivirus ClamAV** : scan des fichiers à l'indexation, fichier infecté **non indexé**
      (testé EICAR) ; statut dans le Header + Paramètres
- [x] Page **Doublons** simplifiée + section Sources unifiée (fin de la saisie manuelle / encart docker-compose)
- [x] **Catalogue universel** : extensions élargies (images, audio, vidéo, doc/ppt/xls, rar/7z…)
      et **configurables en base** (ajout perso) ; exclusion fichiers temp `~$` ; logs pysmb réduits
- [~] **Réorganisation d'arborescence par IA** — incrément 1 livré (proposition + aperçu) ;
      reste : édition drag & drop + application (virtuel → NAS) — cf. plan dédié

---

## 🎯 Besoins prioritaires (le « pourquoi » du projet)

### Phase 1 — Retrouver facilement les fichiers du NAS (v1.8.x)
*Besoin n°1. Le moteur existe ; il faut le brancher sur le vrai volume NAS-MATO et fiabiliser l'usage quotidien.*

- [x] **🔁 Refonte « Dossiers surveillés » → Sources SMB configurables** : ✅ fait — choix du
      serveur (NAS-MATO), **partages SMB listés**, navigation + **cases à cocher**, indexer la
      sélection ; source générique `{type, hôte, chemin, identifiants chiffrés}` en base
      (ajouter un autre serveur sans toucher au compose). Validé sur le vrai NAS.
- [ ] **Indexation continue / planifiée** d'une source (watcher n8n ou cron) — actuellement à la demande
- [ ] **Première indexation complète** du volume NAS + suivi de progression
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
- [ ] **Dédup en 3 passes** (repris d'`ant-tool`) : taille → hash partiel 4 Ko → hash complet,
      pour accélérer le scan sur gros fichiers réseau (NAS)
- [ ] **Quasi-doublons** : détection par similarité sémantique des embeddings (seuil réglable)
- [ ] Bouton « ouvrir l'emplacement » + aperçu du fichier dans chaque ligne
- [ ] **Miniatures / aperçu** des fichiers en double pour faciliter la comparaison visuelle
- [ ] **Photos** : détection des images **floues** (ex. variance du Laplacien) → proposer
      de garder la plus nette et éliminer les floues

### Phase 3 — Grouper / parcourir les documents (v1.10.x)
*Besoin n°3 : grouper par extension, thème/catégorie, …*

- [x] **Liste « tout afficher »** dans la GED : voir tous les documents indexés **sans** lancer
      de recherche (bouton « Tout afficher » + grille paginée « Charger plus »)
- [x] **Ouvrir / consulter un document** depuis la liste (le navigateur ne peut PAS lancer
      l'explorateur Windows ni le logiciel associé → on fournit) :
  - [x] **Aperçu** intégré (`GET /documents/{id}/file` + modal `DocumentPreview` : PDF iframe,
        image, texte/texte extrait ; fallback download pour HEIC/formats non rendus)
  - [x] **Télécharger** l'original (`?download=true`, backend récupère depuis NAS/local)
  - [x] **Copier le chemin** (`chemin_copie` UNC `\\hote\partage\…`) à coller dans l'explorateur
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

📄 **Plan détaillé : [docs/plan-reorganisation-arborescence.md](docs/plan-reorganisation-arborescence.md)**

En bref : l'IA **propose** une arborescence (hybride, ajustable en drag & drop),
**aperçu virtuel** → bouton **« Appliquer au NAS »** (déplacement physique avec
garde-fous + journal d'annulation). Réutilise classification IA + déplacement
fichiers (doublons) + sources local/SMB.

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
- [ ] **Réindexation au renommage** : si un dossier est renommé/déplacé sur le NAS, détecter
      (par hash : même contenu, nouveau chemin) et mettre à jour l'index au lieu de créer des
      doublons / laisser des entrées orphelines
- [x] **Gestion des dossiers indexés (persistante)** : après indexation, la Source **reste** et
      affiche un **arbre des dossiers indexés** (SOURCE → dossier parent déplié → sous-dossiers
      pliés) avec **cases à cocher + tout cocher/décocher** pour **ajouter/retirer** des dossiers
      de l'index (désindexer = retirer de la GED, sans toucher aux fichiers du NAS)
  - [x] Backend : `GET /api/sources/{id}/indexed` (arbre dérivé des docs) + `POST .../deindex`
        (retire de l'index) — testé (745 docs, share `home`)
  - [x] Frontend : `IndexedFolders.tsx` — bouton « Indexés » par source, arbre repliable
        (parent déplié / sous-dossiers pliés) + cases à cocher + tout cocher/décocher +
        bouton « Retirer de l'index » (modale de confirmation) — testé (745 docs)
- [ ] **Système de log / audit** : « qui a fait quoi » — journal des actions (indexation,
      déplacement doublons, ajout/suppression source, désindexation…) avec date + acteur,
      consultable dans l'UI (et lié aux rôles une fois l'auth en place)
- [ ] **Indexation média raisonnée** : ne pas télécharger des Go de vidéos via SMB juste pour
      cataloguer — cataloguer par métadonnées (nom/taille/EXIF) sans fetch complet pour les gros médias

---

## Changelog versionné

Le détail des versions est tenu dans [CHANGELOG.md](CHANGELOG.md).
Chaque release passe par `scripts/release.ps1 -Version X.Y.Z -Message "…"`
(bump `VERSION` + tag `vX.Y.Z` → CI build + verify → images GHCR).
