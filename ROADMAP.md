# ROADMAP — Matothèque

> GED locale intelligente (extraction Tika + IA Ollama + recherche sémantique
> pgvector), 100 % locale. Repo `AgestiTC/ged-local` · cible **NAS-MATO**
> (Synology, 192.168.42.200) · version courante **1.8.0**.

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

### Livré en v1.8.0 (taggé · CI → images GHCR)

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

## 🔎 Retours d'usage (suivi vivant)

> Consigné **au fil des questions/retours** pendant l'utilisation réelle, pour un suivi
> fiable des deux côtés. On coche/déplace au fur et à mesure.

### Session 2026-06-26 — retours sur l'usage post-v1.8.0
- [x] **« Indexations actives » → « Dossiers indexés »** : section renommée, liste les **racines
      indexées par source** (compteur de docs) avec bouton **« Gérer »** qui déplie l'arbre inline
      (cases à cocher + retirer de l'index, réutilise `IndexedFolders`). La surveillance auto
      (dossiers scannés) reste affichée **seulement si** des dossiers sont surveillés.
      (`IndexedSourcesSummary.tsx`)
- [x] **🔴→✅ Indexation média raisonnée (corrigé)** : les **médias (images/audio/vidéo)** sont
      désormais **catalogués par métadonnées** (nom/taille, `statut='catalogued'`) **sans
      téléchargement ni Tika/IA/embeddings** ; les **documents** gardent le pipeline complet.
      `MEDIA_EXTENSIONS`, `ExtractionService.catalogue_media`, `walk_files` renvoie la taille,
      contrainte `documents_statut_check` étendue (garde-fou au démarrage + init-db.sql).
      Validé en conditions réelles : ré-index `home` → **3576 médias `catalogued`** (texte vide,
      sans fetch) + **143 docs `enriched`** (pipeline complet). Dossiers système Synology
      (`#recycle`/`@eaDir`/`#snapshot`) exclus du parcours SMB.
  - [x] **Nettoyage de l'existant** : purge des 9318 docs SMB ingérés en lourd + ré-indexation
        propre de `home` (médias re-catalogués léger). Fait.
  - [ ] **Indexation incrémentale / progression** : la walk SMB est **monolithique** (énumère
        tout l'arbre avant d'insérer → plusieurs minutes sans feedback sur un gros `home`).
        À streamer (insérer au fil du parcours) + barre de progression.
- [x] **GED parcourable par défaut** : la page ouvre directement sur la **liste des documents**
      (mode parcourir) ; les clics **catégorie/tag** du rail **filtrent la liste sans requête**
      (bandeau « Filtré : … ✕ ») ; la recherche bascule en mode résultats, « Tout afficher »/✕
      reviennent à la liste. (`quickFilter` dans GEDPage + prop `filter` d'AllDocumentsView)
- [x] **Page Rapports — écarts vs cahier des charges comblés** :
  - [x] **multi-sélection Shift+clic** (sélection de plage) dans le picker (`selectMany`)
  - [x] indicateur **tokens / temps estimés** (`GenerationEstimate`) + alerte troncature si > fenêtre modèle
  - [x] bouton **« Régénérer »** dans la barre d'outils du résultat
  - [x] picker Rapports **n'affiche plus les médias catalogués** (filtre backend `texte=true`)
  - [~] colonne gauche en **liste plate** : re-scopée — le picker plat (+ « Sources ») remplace
        l'« arborescence de dossiers surveillés » du plan initial. Regroupement par dossier
        optionnel plus tard si besoin.
- Clarifications (pas un bug) : l'**arbre des dossiers indexés** = bouton **« Indexés »** sur la
  source ; l'indexation SMB est un **traitement one-shot** qui alimente la GED + cet arbre.

### Session 2026-06-27 — idées UI GED (pour plus tard)
- [~] **Vue cartes (vs lignes) dans la GED** : la vue « Tout afficher » est déjà en **cartes**
      (aperçu / fiche IA / télécharger / copier). Reste : **bascule cartes ⇄ liste** + appliquer
      aussi le format carte aux **résultats de recherche** (aujourd'hui encore en cartes simples).
- [x] **Tags éditables** : accessibles via le bouton **✨ Fiche** des cartes → tiroir `DocumentCard`
      (résumé éditable, catégorie, entités, **tags ajout/retrait** via `TagManager`).
      Reste optionnel : édition des tags **directement** sur la carte (sans ouvrir la fiche).
- [x] **Rationaliser la colonne de gauche de la GED** — fait :
  - **MODE** (Hybride/Texte/Sémantique) déplacé **sous la barre de recherche** (« Recherche : … »).
  - **CATÉGORIES / TAGS** masqués quand une **vue groupée** est active (doublon avec « Grouper
    par ») + indice dans le rail.
  - **IMPORTER (déposer/cliquer)** retiré de la GED (l'ajout passe par **Paramètres → Sources** ;
    le drag&drop reste dans **Rapports**).
- [ref] **Fonctionnement de la recherche** (réponse consignée) :
  - **Texte (full-text PostgreSQL fr)** : cherche les **mots** dans le **texte extrait**
    (corps + titres de paragraphes tels qu'extraits par Tika) **+ le nom du fichier** ;
    gère pluriels/conjugaisons (racines) mais reste **mot-à-mot**.
  - **Sémantique (embeddings)** : cherche par **sens/idée** → trouve des docs proches **sans les
    mêmes mots** (« voiture » ≈ « véhicule »). C'est « l'idée du document d'après l'IA ».
  - **Hybride** (défaut) : fusion **40 % texte / 60 % sémantique** (scores normalisés).
  - **Pas** cherchés par la requête : **catégorie / tags / résumé IA** (ce sont des **filtres**,
    pas du plein-texte). → **Décidé : on ne les ajoute PAS au plein-texte** — redondant (le
    sémantique trouve déjà par le sens, catégories/tags = filtres, le résumé reprend le texte
    déjà indexé). « Si inutile, on n'ajoute pas. »

### Cosmétique (pour plus tard)
- [x] **Retirer le titre « Matothèque »** redondant du top bar (déjà présent dans la barre
      latérale) — fait (Header n'affiche plus que les statuts services).
- [ ] **Menu en barre horizontale (haut)** au lieu de la **colonne verticale gauche**, en suivant
      la **norme du `_modele`** (modèle docker AgestiTC). À aligner sur le layout du modèle.
- [ ] **Navigation ← / →** : boutons précédent/suivant pour revenir à l'action / la carte / la vue
      précédente (et avancer). Historique de navigation interne (fiche, aperçu, filtre, recherche).
- [ ] **Refonte page Paramètres — regrouper par fonction, sections pliables/dépliables** :
      aujourd'hui 9 sections en **un seul long scroll** (Import direct · Sources · Dossiers indexés ·
      Prompts · Templates · Statistiques · Maintenance · Services & modèles IA · À propos).
      **Plan proposé** :
  - Composant réutilisable `CollapsibleSection` (titre + icône + chevron, ouvert/fermé,
    état mémorisé en `localStorage`). Option : mini sous-menu d'ancres en haut pour sauter à un groupe.
  - **Regroupement par fonction** (4 accordéons) :
    1. **📁 Sources & indexation** : Sources de fichiers · Dossiers indexés (+ surveillance auto) · Import direct
    2. **🤖 IA & services** : Services & modèles IA (URLs Tika/Ollama/n8n, test, statut, modèles, MAJ)
    3. **📝 Génération** : Prompts pré-enregistrés · Templates
    4. **⚙️ Système** : Statistiques · Maintenance · À propos
  - Par défaut : **Sources & indexation** ouvert, le reste plié (réduit le scroll).
  - Étapes : créer `CollapsibleSection` → envelopper chaque section existante (aucune logique
    métier modifiée, pur réagencement) → vérif visuelle.
- [ ] **Statut « en cours d'analyse »** lisible : pour un doc pas encore enrichi par l'IA
      (`pending`/`extracted`), afficher un libellé clair type « ⏳ en cours d'analyse » au lieu de
      « pas de tags » (qui ressemble à un bug).
- [ ] **Déplacer un fichier vers une corbeille « À supprimer »** (depuis n'importe quel fichier
      de la GED) : **icône discret mais sans équivoque** sur la carte + **confirmation** avant
      déplacement (2 boutons **Annuler / Confirmer**). Étend la **quarantaine des doublons**
      (`DOUBLON-MATOTEQUE`) à **tous** les fichiers. Dossier cible type `A-SUPPRIMER-MATOTEQUE/`
      à la racine du partage ; retirer aussi de l'index ; idéalement **journal + annulation**.
      ⚠️ **Prérequis : écriture SMB** (déplacer un fichier sur le NAS) — capacité nouvelle
      (`pysmb` rename/createDirectory/deleteFiles), aujourd'hui on ne fait que **lire**.
      **Destructif** → garde-fous. Mutualisable avec **Réorganisation incrément 2** (même
      plomberie SMB-write + undo).
- [ ] **🐞 Fiabilité enrichissement IA — `enriched` sans `metadonnees_ia`** : ~51 docs ont du
      texte (>500 car) mais **aucune fiche IA**. Cause : le modèle rapide renvoie parfois une
      réponse **non-JSON** → `JSONDecodeError` attrapé (extraction.py:394), méta **ignorée
      silencieusement**, mais le doc reste marqué `enriched`. Fix : forcer **`format=json`**
      côté Ollama + **1 retry**, et **ne pas marquer `enriched`** si la méta a échoué (statut
      distinct / re-enrichissable). Concerne **toutes** extensions (pas spécifique XLSX/TXT/ZIP).
- [ ] **Extraction des ZIP — détail (à arbitrer avant code)** : `process_zip` (Tika `/rmeta`,
      1 doc par fichier interne) **existe déjà mais seulement pour les ZIP UPLOADÉS** ; les ZIP
      **indexés via SMB** passent par `process_file` → uniquement la **liste des noms**. Deux options :
  - **A. Liste des fichiers dans la fiche IA** (léger, = la demande) : présenter proprement la
    liste des fichiers internes (déjà dans `texte_extrait`) dans la fiche. Aucune décompression,
    zéro risque, le ZIP reste 1 entrée. ← **recommandé en premier**.
  - **B. Extraction du contenu interne** (lourd) : router les ZIP SMB vers `process_zip` →
    chaque fichier interne devient cherchable (texte + IA). Mais télécharge le ZIP, **explose le
    nb de docs** (1 ZIP = N docs) et le coût IA → garde-fous (taille max, médias internes
    catalogués léger). À faire si on veut chercher **dans** les zips.

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
- [x] **Vue groupée** de la GED : regroupement par **extension** (PDF, DOCX, XLSX…)
- [x] Regroupement par **thème / catégorie IA** (avec bucket « non classé ») et par **tags**
  - [x] `GET /documents/groups?by=…` + filtre `?categorie=` ; UI « Grouper par » dans « Tout
        afficher », groupes repliables à chargement paresseux (`AllDocumentsView.tsx`) — testé
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
