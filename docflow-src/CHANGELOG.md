# Changelog — DocFlow AI

Toutes les modifications notables de ce projet sont documentées ici.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/)
Versioning : [Semantic Versioning](https://semver.org/lang/fr/)

---

## [Unreleased]

### En cours
- Optimisations performances (index pgvector ivfflat tuning)

---

## [v1.3.0] — 2026-04-13

### Couverture de tests complète — tous les routers backend + hooks frontend

**Tests backend — nouveaux fichiers :**
- `test_folders_router.py` : 20 tests
  - `TestListFolders` : liste vide, liste peuplée, structure réponse
  - `TestAddFolder` : ajout dossier existant (mock Path), chemin inexistant (422), doublon (409), nom_affichage personnalisé
  - `TestUpdateFolder` : actif, nom, partiel (autres champs conservés), intervalle min 30s (422), inexistant (404), ID invalide
  - `TestRemoveFolder` : suppression OK, absent après, avec documents associés (`supprimer_documents=true`), inexistant, ID invalide
  - `TestForceScan` : dossier actif (200), dossier inactif (422), inexistant (404), ID invalide
  - `TestBrowseFilesystem` : chemin valide (dossiers + fichiers), inexistant (404), chemin_parent, filtre extensions, taille fichier
- `test_upload_router.py` : 12 tests
  - Acceptés : PDF, DOCX, XLSX — rejetés : TXT, JPG (statut="rejeté" + raison)
  - Multi-fichiers en une requête ; mélange acceptés/rejetés dans une même réponse
  - Job créé en DB après upload (statut="pending", type="extraction")
  - ZIP : accepté via `/upload/zip`, rejeté si non-ZIP (400), paramètre type="zip" dans le job
- `test_extract_router.py` : 18 tests
  - `TestGetJobStatus` : pending/completed/failed, structure réponse, inexistant (404), ID invalide
  - `TestRelancerExtraction` : doc existant → job créé, doc repasse en "pending", fichier source manquant (422), inexistant (404), ID invalide
  - `TestListJobs` : liste vide, filtre statut, filtre type, limite, structure, ordre décroissant (plus récent en premier)

- `test_templates_router.py` : 20 tests
  - `TestListTemplates` : liste vide, templates peuplés, structure réponse (sans champs), ordre alphabétique
  - `TestUploadTemplate` : DOCX accepté (201), PDF accepté (nb_champs=0), extension TXT rejetée (400), champs `{{ }}` détectés, nom_affichage généré (title case), template créé en DB
  - `TestGetTemplate` : template existant avec champs, structure champs (nom/type/description), inexistant (404), ID invalide (400)
  - `TestDeleteTemplate` : suppression OK avec message, absent après, fichier physique supprimé, fichier manquant OK, inexistant (404), ID invalide, double suppression (404)

**Tests frontend — nouveau fichier :**
- `useDropZone.test.ts` : 16 tests
  - Types MIME acceptés : PDF, DOCX, XLSX, PPTX+PPSX, ZIP, ODT/ODS/ODP
  - `multiple: true` transmis à react-dropzone
  - `onDrop` délègue à `uploadFiles` du store ; ne l'appelle pas si liste vide
  - Transmet tous les fichiers d'un dépôt multi-fichiers
  - `noClick` : false par défaut, true/false transmis correctement
  - Valeur retournée : `getRootProps`, `getInputProps`, `isDragActive`, `open`

---

## [v1.2.0] — 2026-04-13

### Couverture de tests étendue + hook useSearch mis à jour

**`useSearch.ts` :**
- Expose désormais `hasMore`, `currentOffset`, `loadingMore`, `loadMore` (pagination GED)

**Tests backend nouveaux :**
- `test_documents_router.py` : 22 tests
  - `TestListDocuments` : liste vide, filtres statut/extension/nom, pagination, structure réponse
  - `TestDocumentStats` : base vide, agrégation taille + total, endpoint avant `/{id}` (régression)
  - `TestGetDocument` : doc existant, avec/sans métadonnées, inexistant, ID invalide
  - `TestGetDocumentText` : texte extrait, texte vide (null → ""), doc inexistant
  - `TestPatchMetadata` : tags, catégorie, résumé, sans meta (404), champs non fournis conservés
  - `TestGetVersions` : sans versions, avec versions (ordre décroissant), doc inexistant
  - `TestDeleteDocument` : suppression OK, absent après suppression, inexistant (404), ID invalide
- `test_prompts_router.py` : 17 tests
  - `TestListPrompts` : liste + structure réponse
  - `TestCreatePrompt` : création 201, nom vide (422), prompt_text vide (422), champs optionnels, ID UUID
  - `TestUpdatePrompt` : modification nom, modification partielle (autres champs conservés), inexistant (404), ID invalide
  - `TestDeletePrompt` : suppression OK, absent après suppression, inexistant (404), ID invalide, double suppression (404)

**Tests frontend hooks :**
- `useDocuments.test.ts` : 18 tests — expose documents/total/page/loading/error, selectedCount dérivé, toutes les actions (toggleSelect/selectAll/deselectAll/isSelected/selectDocument/deselectDocument)
- `useSearch.test.ts` : 18 tests — expose query/results/total/loading/error + `hasMore/currentOffset/loadingMore`, toutes les actions + search/loadMore guards

---

## [v1.1.0] — 2026-04-13

### Tests + Onglet texte extrait + Pagination affinée

**gedStore — tests de pagination :**
- `gedStore.test.ts` entièrement reécrit : 20 tests couvrant setters, search(), loadMore(), loadTags/loadCategories
- Mock de base `BASE_SEARCH_RESPONSE` avec `has_more/offset/limit` requis par le nouveau type
- `RESET_STATE` commun (inclut `hasMore/currentOffset/loadingMore`) pour isolation des tests
- `loadMore()` : 6 nouveaux tests (accumulation, offset passé à l'API, guards hasMore/query/loadingMore, reset en erreur)

**DocumentCard — onglet "Texte extrait" :**
- Ajout système d'onglets "Métadonnées" | "Texte extrait" avec indicateur actif (bordure bleue)
- Chargement paresseux du texte : `GET /documents/{id}/text` appelé uniquement à l'activation de l'onglet
- Bouton "Copier" avec feedback "Copié !" (2 secondes) via `navigator.clipboard`
- Compteur de caractères affiché dans la toolbar de l'onglet texte
- Reset de l'état texte quand `documentId` change

**Tests backend — search pagination :**
- `test_search_pagination.py` : 9 tests
  - Champs `has_more/offset/limit` présents dans toute réponse
  - `has_more=false` si résultats < limit
  - `has_more=true` si résultats > limit
  - Décalage correct entre page 1 (offset=0) et page 2 (offset=20) — IDs non-chevauchants
  - Offset négatif rejeté (422)
  - Offset par défaut = 0
  - Total stable entre pages
  - Filtre catégorie appliqué avant pagination (15 rapports sur 25 docs = total=15)

---

## [v1.0.0] — 2026-04-13

### Production-ready : Outillage + Pagination GED + Tests generate

**Makefile :**
- `make help` : liste toutes les cibles avec documentation inline
- `make up / down / logs / build / restart` : cycle de vie Docker
- `make test / test-backend / test-frontend / test-e2e / test-e2e-mocked` : tous les tests
- `make migrate / migrate-create / migrate-history / migrate-downgrade` : gestion Alembic
- `make dev-backend / dev-frontend / install / install-playwright` : développement local
- `make lint / lint-backend / lint-frontend / format / typecheck` : qualité de code
- `make health` : vérification état Tika + Ollama + backend en une commande
- `make clean / clean-docker / reset` : nettoyage environnement

**Pagination GED (backend + frontend) :**
- `GET /search` : ajout paramètre `offset` (ge=0), retourne `has_more`, `offset`, `limit` dans la réponse
- `searchApi.search()` : paramètre `offset` ajouté dans le type TypeScript
- `gedStore` : ajout `hasMore`, `currentOffset`, `loadingMore`, action `loadMore()` (accumulation des résultats)
- `GEDPage` : bouton "Charger plus de résultats" (visible si `hasMore`), spinner pendant `loadingMore`, message "Tous les N résultats" quand complet

**Tests backend — generate router :**
- `test_generate_router.py` : 14 tests
  - `TestListModels` : retour modèles Ollama, fallback si indisponible, format `{name}`
  - `TestGenerateReport` : document_ids vide (400), UUID invalide (400), document inexistant (404), prompt vide (422), rapport avec doc existant (200 + job_id + stream_url), modèle par défaut
  - `TestGenerationStatus` : job inexistant (404), ID invalide (400), statut après création
  - `TestConstruireContexte` : contexte simple, doc sans texte ignoré, troncature marquée, plusieurs documents

**Corrections E2E :**
- `mockModelsAPI` : route corrigée de `**/api/tags` → `**/api/generate/models` (proxy backend, pas Ollama direct)

---

## [v0.5.0] — 2026-04-13

### Migrations Alembic + Tests E2E Playwright

**Migrations Alembic (production-ready) :**
- `alembic.ini` : configuration Alembic avec async, template de nommage daté
- `alembic/env.py` : env async compatible asyncpg, lit `DATABASE_URL` depuis l'environnement
- `alembic/script.py.mako` : template de migration avec type hints
- `alembic/versions/20260413_0001_initial_schema.py` : migration initiale complète
  - Extensions : `vector`, `pg_trgm`
  - Tables : `documents`, `metadonnees_ia`, `embeddings` (colonne `vector(4096)`), `versions`, `templates`, `prompts_presets`, `jobs`, `dossiers_surveilles`
  - Index : trgm pour nom, GIN pour full-text, IVFFlat pour embeddings, GIN pour tags

**Tests E2E Playwright :**
- `playwright.config.ts` : config Chromium, retries CI, webServer Vite auto, reporters HTML
- `package.json` : scripts `test:e2e` et `test:e2e:ui`, dépendance `@playwright/test`

**Tests E2E sans backend (mocked) :**
- `e2e/fixtures.ts` : données mock, helpers `mockDocumentsAPI`, `mockSearchAPI`, `mockFoldersAPI`, `mockTagsAndCategoriesAPI`, `mockModelsAPI`, `mockHealthAPI` + fixture `mockedPage`
- `e2e/mocked/reports-mocked.spec.ts` : documents dans la liste, sélection + compteur, activation bouton générer, tout sélectionner/désélectionner
- `e2e/mocked/ged-mocked.spec.ts` : catégories/tags sidebar, résultats de recherche, score, panneau latéral, effacer, filtre par tag

**Tests E2E avec backend réel :**
- `e2e/navigation.spec.ts` : page par défaut, sidebar, navigation entre pages, layout de base
- `e2e/reports.spec.ts` : prompt editor, modes de sortie (rapport/template/classement), validation formulaire
- `e2e/ged.spec.ts` : barre de recherche, modes, état vide, drag & drop
- `e2e/upload.spec.ts` : zone dropzone, types de fichiers, retour API upload

**Autres :**
- `requirements.txt` : ajout `aiosqlite==0.20.0` pour les tests SQLite async

---

## [v0.4.0] — 2026-04-13

### Phase 4 — Polish : Tests + Templates + n8n

**Tests backend (pytest) :**
- `conftest.py` : fixtures SQLite en mémoire, mocks Tika/Ollama/EmbeddingService, client HTTP de test
- `test_chunker.py` : 9 tests unitaires pour `chunk_text()` (vide, taille, overlap, couverture)
- `test_hash_utils.py` : 6 tests pour `compute_sha256()` (cohérence, format, hash connu, 5 MB)
- `test_extraction.py` : tests `_extraire_json` + 7 tests intégration `ExtractionService` (déduplication, erreurs Tika/Ollama, création MetadonneeIA)
- `test_export_router.py` : endpoints DOCX/PDF + `_nom_export` (sanitisation, troncature, horodatage)
- `test_search_service.py` : pondération fusion 40/60, union IDs, fallback embedding
- `pytest.ini` : `asyncio_mode = auto`, `testpaths = tests`

**Tests frontend (vitest) :**
- `__tests__/setup.ts` : stub `EventSource`, `crypto.randomUUID`, `import.meta.env`
- `stores/documentStore.test.ts` : 13 tests (sélection, fetch, delete, upload jobs)
- `stores/reportStore.test.ts` : 12 tests (setters, streaming, historique, erreurs)
- `stores/gedStore.test.ts` : 13 tests (recherche, filtres, tags, catégories)
- `hooks/useReport.test.ts` : logique `canGenerate` + `generate()` avec selectedIds
- `utils/typeUtils.test.ts` : 16 tests (statuts, poids fusion, pagination, sanitisation, formatTaille)
- `vite.config.ts` : configuration vitest (globals, jsdom, setupFiles, coverage)

**Services backend complétés :**
- `TemplateFiller` : detect_fields → prompt LLM → parse JSON → docxtpl.render → export DOCX
- `FolderWatcher` : polling async, mtime comparison, fichiers cachés filtrés
- `SearchService` : `_fusionner()` 40/60, recherche sémantique avec fallback, `_charger_resultats()`
- `GEDService` : `get_documents()`, `detect_duplicate()`, `get_stats()`
- `ExportService` : CSS complet weasyprint PDF, parser ligne par ligne python-docx DOCX
- `ReportGenerator` : `generate_stream()`, `build_context()`, `_charger_textes()`
- `main.py` : seed prompts idempotent depuis `scripts/seed-prompts.json` au startup

**Workflows n8n :**
- `folder-watcher.json` : ScheduleTrigger (5 min) → GET /api/folders → POST /api/folders/{id}/scan
- `indexer.json` : Cron (2h) → GET documents extracted/error → POST /api/extract/{id} → log
- `report-pipeline.json` : Webhook POST → validate → POST /api/generate/report → respondToWebhook

---

## [v0.3.0] — 2026-04-13

### Phase 3 — GED avancée

**Composants GED :**
- `DocumentCard` : fiche complète (métadonnées, résumé éditable, entités, tags, versions, actions)
- `TagManager` : tags éditables inline (ajout/suppression, `PATCH /api/documents/{id}/metadata`)
- `VersionHistory` : historique des versions avec diff résumé par IA
- `SearchBar` : toggle type (Hybride/Texte/Sémantique), loading state, submit/clear
- `CategoryBrowser` : filtre actif avec ✕, click → setFilters + search()

**Composants reports complétés :**
- `PromptPresets` : dropdown groupé par catégorie, overlay + outside click
- `GenerateButton` : lecture selectedIds + prompt + isGenerating, Loader2 animate-spin
- `OutputMode` : sélecteur 3 modes (rapport libre, remplir template, classement)
- `TemplateUpload` : upload template DOCX + détection champs {{ }} via API

**Composants fichiers complétés :**
- `FileCard` : dot statut coloré, toggle CheckSquare/Square, hover actions (relance/suppression)
- `FolderSelector` : navigation arborescence filesystem via API browse, sélection dossier

**Composants common complétés :**
- `ErrorBoundary` : getDerivedStateFromError, retry button, componentDidCatch

**Hooks :**
- `useDocuments` : wrapper documentStore + `selectedCount`
- `useReport` : wrapper reportStore + `canGenerate` + `generate()`
- `useSearch` : wrapper gedStore
- `useDropZone` : react-dropzone + uploadFiles, 9 types MIME acceptés

**Pages mises à jour :**
- `ReportsPage` : OutputMode selector, TemplateUpload conditionnel, GenerateButton, badge sélection
- `GEDPage` : panneau latéral DocumentCard (w-80, wired avec selectedDocId)

**Backend :**
- Router `search.py` : correction GROUP BY sémantique, endpoint `PATCH /api/documents/{id}/metadata`

---

## [v0.2.0] — 2026-04-13

### Backend — Implémentation complète Phase 1 + 2

**Pipeline d'extraction :**
- `ExtractionService.process_file()` : hash SHA256 → dédup → Tika → enrichissement IA (Ollama) → embeddings pgvector
- `ExtractionService.process_zip()` : extraction de chaque fichier ZIP via Tika `/rmeta`
- `EmbeddingService.embed_document()` : chunking → embed par chunk + fallback modèle
- Prompt d'enrichissement IA → JSON parsé robustement (gère ```json```, texte brut, extraction regex)

**Routers FastAPI implémentés :**
- `/api/upload` — multipart + background tasks + polling jobs
- `/api/extract` — status jobs, relance
- `/api/documents` — CRUD + pagination + filtres (statut, extension, source, nom)
- `/api/generate` — génération rapport + SSE streaming temps réel
- `/api/search` — recherche hybride (PostgreSQL full-text 40% + pgvector cosine 60%)
- `/api/export` — Markdown → PDF (weasyprint) + DOCX (python-docx)
- `/api/folders` — CRUD dossiers surveillés + scan en background + browse filesystem
- `/api/prompts` — CRUD prompts pré-enregistrés
- `/api/templates` — upload DOCX + détection champs `{{ champ }}`
- `main.py` — startup : init DB + health check Tika/Ollama (non bloquant)

### Frontend — Interface complète Phase 2

**Couche données :**
- `api/index.ts` : fonctions typées pour tous les endpoints backend
- `documentStore` : liste, sélection multi, upload + polling jobs, delete, relance
- `reportStore` : prompt, modèle, génération SSE, historique, export
- `gedStore` : recherche hybride, filtres, tags, catégories

**Composants :**
- `Sidebar` : navigation + indicateur version
- `Header` : statut Tika/Ollama (ping toutes les 30s)
- `Toast` : système notifications (success/error/info)
- `DropZone` : drag & drop fichiers/ZIP avec react-dropzone + feedback visuel
- `FileExplorer` : liste documents avec statut coloré, sélection multi, actions
- `PromptEditor` : textarea + dropdown presets + sauvegarde API
- `ModelSelector` : dropdown modèles Ollama chargés dynamiquement
- `ReportPreview` : aperçu Markdown rendu + streaming cursor + export PDF/DOCX

**Pages :**
- `ReportsPage` : layout 3 colonnes (fichiers | config | résultat)
- `GEDPage` : recherche hybride + filtres catégories/tags + grille cartes
- `SettingsPage` : gestion dossiers surveillés + état services + ajout/scan/suppression

---

## [v0.1.0] — 2026-04-10

### Ajouté
- Structure complète du projet (backend, frontend, scripts, documentation)
- Configuration Docker Compose avec volumes mappés sur l'hôte (aucune donnée dans les conteneurs)
- Squelette FastAPI avec tous les modules, routers, services, modèles
- Squelette React + Vite + TailwindCSS avec tous les composants
- Configuration du logging structuré (structlog JSON)
- Schéma PostgreSQL + pgvector (init-db.sql)
- Stubs workflows n8n (folder-watcher, indexer, report-pipeline)
- Documentation initiale (architecture, API, DB, guides)
- .gitignore adapté au projet
- CHANGELOG.md (ce fichier)

### Infrastructure
- PostgreSQL 16 + pgvector : données sur `./data/postgres/` (hôte)
- Uploads : `./storage/uploads/` (hôte)
- Exports : `./storage/exports/` (hôte)
- Templates : `./storage/templates/` (hôte)
- Logs : `./logs/` (hôte)
- Documents surveillés : chemin configurable via `DOCUMENTS_ROOT` dans `.env`

---

## Roadmap versions

| Version | Contenu | Statut |
|---------|---------|--------|
| `v0.1.0` | Scaffold + structure | ✅ |
| `v0.2.0` | Backend complet (Tika + Ollama + DB) + Frontend Phase 2 | ✅ |
| `v0.3.0` | GED avancée (DocumentCard, TagManager, VersionHistory, panneau latéral) | ✅ |
| `v0.4.0` | Polish : tests, services complets, n8n workflows | ✅ |
| `v0.5.0` | Migrations Alembic + tests E2E Playwright | ✅ |
| `v1.0.0` | Makefile + pagination GED + tests generate router | ✅ |
| `v1.1.0` | Onglet texte extrait + tests pagination + gedStore tests | ✅ |
| `v1.2.0` | test_documents_router + test_prompts_router + useDocuments/useSearch tests | ✅ |
