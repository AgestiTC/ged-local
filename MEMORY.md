# MEMORY.md — DocFlow AI

## Identité du projet

- **Nom** : DocFlow AI
- **Type** : Plateforme locale de gestion documentaire intelligente + génération de rapports
- **Philosophie** : 100% local, aucun cloud, IA locale via Ollama
- **Langue de l'utilisateur** : Français
- **Langue du code** : Anglais (variables, fonctions), commentaires en français

---

## Stack de l'utilisateur (déjà installée sur sa machine)

- **Ollama** — serveur LLM local (`http://localhost:11434`)
- **Apache Tika** — extraction documentaire universelle (`http://localhost:9998`)
- **n8n** — orchestration de workflows (`http://localhost:5678`)
- **Open-WebUI** — chat IA séparé (ne fait pas partie de ce projet)

### Modèles Ollama disponibles

- `mixtral:latest` (26 GB) → modèle principal pour rapports et raisonnement
- `llama3.1:latest` (4.9 GB) → alternative rapide
- `mistral:latest` (4.4 GB) → tâches légères, extraction de champs
- `glm-ocr:latest` (2.2 GB) → OCR avancé
- `llava:latest` (4.7 GB) → analyse d'images
- `qwen3-embedding:8b` (4.7 GB) → embeddings principal (vérifier la dimension exacte)
- `nomic-embed-text:latest` (274 MB) → embeddings léger fallback
- `ministral-3:14b` (9.1 GB) → usage alternatif

---

## Deux modules du projet

### Module 1 : DocFlow Reports

Génération de rapports et classements à partir de documents.

**Fonctionnalités clés :**
- Surveillance automatique de dossiers (fichiers évoluent en continu)
- Interface web : sélection de dossiers/fichiers + drag & drop (fichiers, dossiers, ZIP)
- Éditeur de prompt avec presets
- Choix du modèle Ollama
- 3 modes de sortie : rapport libre, remplissage de template DOCX/PDF, classement/tri
- Prévisualisation du résultat + export PDF/DOCX
- Streaming SSE pour affichage progressif du rapport

**Formats supportés** : PDF, DOCX, PPTX, PPSX, XLSX, ZIP

### Module 2 : DocFlow GED

Gestion Électronique de Documents locale.

**Fonctionnalités clés :**
- Indexation automatique de tous les documents
- Recherche hybride : full-text (PostgreSQL) + sémantique (pgvector + embeddings)
- Classification automatique par IA (catégorie, tags, résumé, entités)
- Gestion des versions (détection automatique quand un fichier change)
- Détection de doublons par hash SHA256
- Dossiers virtuels et tags éditables

---

## Décisions techniques prises

| Décision | Choix | Raison |
|----------|-------|--------|
| Base de données | PostgreSQL 16 + pgvector | Unifie SQL, full-text, et vectoriel. Pérenne pour la GED |
| Backend | FastAPI (Python 3.11+, async) | Écosystème Python riche pour docs, performance async |
| Frontend | React 18 + TypeScript + Vite + Tailwind | Standard moderne, react-dropzone pour drag & drop |
| State management | Zustand | Plus léger que Redux, suffisant pour ce projet |
| Appels API frontend | TanStack Query (React Query) | Cache, refetch, mutations |
| Extraction docs | Apache Tika (déjà installé) | Universel, tous formats, une seule API HTTP |
| Embeddings principal | qwen3-embedding:8b | Meilleure qualité que nomic-embed-text |
| Templates DOCX | docxtpl (Jinja2) | Syntaxe simple {{ champ }}, bien maintenu |
| Export PDF | weasyprint | Conversion markdown/HTML → PDF |
| Export DOCX | python-docx | Génération DOCX programmatique |
| Migrations DB | Alembic | Standard avec SQLAlchemy |
| Drag & drop | react-dropzone + webkitGetAsEntry API | Supporte fichiers, dossiers, ZIP |
| Logging | structlog (JSON) | Structuré, facile à filtrer |
| Conteneurisation | Docker Compose | Ollama et n8n restent sur l'hôte |

---

## Schéma de base de données

Tables principales (détails complets dans CLAUDE.md) :
- `documents` — fichiers indexés + texte extrait + métadonnées Tika
- `metadonnees_ia` — enrichissement IA (catégorie, tags, résumé, entités)
- `embeddings` — chunks vectoriels pour recherche sémantique
- `versions` — historique des modifications de fichiers
- `templates` — templates DOCX/PDF pour le remplissage
- `prompts_presets` — prompts pré-enregistrés
- `jobs` — file d'attente des tâches (extraction, enrichissement, rapport)
- `dossiers_surveilles` — dossiers à surveiller automatiquement

---

## État d'avancement — v0.5.0 (complet)

### ✅ Phases 1 + 2 — Backend + Frontend

**Backend (Python / FastAPI) — 100% :**
- Modèles SQLAlchemy, TikaService, OllamaService, EmbeddingService, ExtractionService
- Tous les routers : upload, extract, documents (+ /stats avant /{id}), generate (SSE + proxy /models), search, export, folders, prompts, templates
- main.py : startup init DB + seed prompts + health checks
- Migrations Alembic async : alembic.ini, env.py (asyncio.run), migration initiale complète avec pgvector

**Frontend (React / TypeScript) — 100% :**
- Stores Zustand (documentStore, reportStore, gedStore) + hooks (useDocuments, useReport, useSearch, useDropZone)
- Tous les composants : DropZone, FileExplorer, FileCard, FolderSelector, PromptEditor, PromptPresets, ModelSelector (proxy backend), OutputMode, TemplateUpload, GenerateButton, ReportPreview, SearchBar, CategoryBrowser, DocumentCard, TagManager, VersionHistory, LoadingSpinner, Toast, ErrorBoundary
- Pages : ReportsPage (3 colonnes), GEDPage (panneau latéral document), SettingsPage (stats + catégories + services)

### ✅ Phase 3 — GED avancée
- DocumentCard : fiche complète avec métadonnées, résumé éditable, entités, tags, versions
- TagManager : tags éditables inline (PATCH metadata)
- VersionHistory : historique + diff IA
- GEDPage : panneau latéral wired avec selectedDocId

### ✅ Phase 4 — Polish
- Tests backend : conftest.py, test_chunker, test_hash_utils, test_extraction, test_export_router, test_search_service
- Tests frontend : setup.ts, documentStore.test, reportStore.test, gedStore.test, useReport.test, typeUtils.test
- Services complétés : TemplateFiller (docxtpl), FolderWatcher (polling async), SearchService, GEDService, ExportService, ReportGenerator
- Workflows n8n : folder-watcher.json, indexer.json, report-pipeline.json
- pytest.ini configuré, vitest configuré dans vite.config.ts

### ✅ Phase 5 — Tests E2E + Alembic + Outillage
- Playwright E2E : playwright.config.ts, fixtures.ts avec mockedPage, 4 suites réelles + 3 suites mockées
- Makefile : help, up/down/logs/build, test/test-backend/test-frontend/test-e2e, migrate, lint, format, health, clean
- SettingsPage : stats (total, volume, enrichis), répartition statuts, catégories avec barres de progression
- ModelSelector : proxy via backend /generate/models (évite CORS Ollama)
- statsApi + DocumentStats type dans frontend/src/api/index.ts

### ✅ v1.0.0 — Production-ready
- Makefile : help/up/down/test/migrate/lint/health/clean — toutes les commandes dev en une cible
- Pagination GED : offset backend + hasMore/loadMore store + bouton "Charger plus" GEDPage
- test_generate_router.py : 14 tests (list_models, generate_report, status, _construire_contexte)
- mockModelsAPI E2E corrigé : route `**/api/generate/models` (proxy backend, pas Ollama direct)

### ✅ v1.1.0 — Tests + Onglet texte + Pagination affinée
- gedStore.test.ts reécrit (20 tests, pagination loadMore, BASE_SEARCH_RESPONSE, RESET_STATE)
- DocumentCard : onglets Métadonnées / Texte extrait, chargement paresseux, bouton Copier
- test_search_pagination.py : 9 tests (has_more, offset, filtre avant pagination)

### ✅ v1.2.0 — Tests routers documents + prompts + hooks frontend
- useSearch.ts : expose hasMore, currentOffset, loadingMore, loadMore
- test_documents_router.py : 22 tests (list, stats, get, text, PATCH metadata, versions, delete)
- test_prompts_router.py : 17 tests (CRUD complet, validation, double DELETE)
- useDocuments.test.ts : 18 tests (selectedCount, toggleSelect, selectAll, isSelected)
- useSearch.test.ts : 18 tests (pagination fields, guards loadMore, clearResults)

### ✅ v1.3.0 — Couverture tests complète (tous les routers + hooks)
- test_folders_router.py : 20 tests (CRUD, scan forcé, browse filesystem, mock Path)
- test_upload_router.py : 12 tests (multipart, acceptés/rejetés, ZIP, jobs en DB)
- test_extract_router.py : 18 tests (status job, relance extraction, liste jobs filtrée)
- test_templates_router.py : 20 tests (CRUD, upload DOCX/PDF, champs détectés, fichier physique)
- useDropZone.test.ts : 16 tests (types MIME, délégation upload, noClick, valeur retournée)

### 🔲 Restant
- Optimisations pgvector (ivfflat lists tuning selon volume données réelles)
- Vérifier dimension exacte embeddings qwen3-embedding:8b au premier démarrage réel
- Déploiement production end-to-end (docker compose up complet)

---

## Points d'attention à garder en mémoire

1. **Tika est déjà installé** — ne pas recoder l'extraction, appeler Tika via HTTP
2. **Ollama est sur l'hôte** — le backend Docker y accède via `host.docker.internal:11434`
3. **Mixtral = 26 GB de RAM** — prévoir une file d'attente, pas de parallélisme LLM
4. **Contexte Mixtral = 32k tokens** — tronquer si documents combinés dépassent
5. **Drag & drop de dossiers** — nécessite `webkitGetAsEntry()`, pas standard mais supporté
6. **Les fichiers dans les dossiers surveillés évoluent** — la surveillance doit être continue
7. **Dimension embeddings qwen3-embedding:8b** — à vérifier au premier test, adapter le schéma
8. **L'utilisateur est francophone** — interface en français, messages en français
9. **ZIP** — Tika extrait chaque fichier via `/rmeta`, un document par fichier dans le ZIP
10. **Templates DOCX** — syntaxe `{{ champ }}` avec docxtpl, le LLM retourne du JSON

---

## Commandes utiles

```bash
# Tester Tika
curl -T fichier.pdf http://localhost:9998/tika --header "Accept: text/plain"
curl -T fichier.pdf http://localhost:9998/rmeta --header "Accept: application/json"

# Tester Ollama
curl http://localhost:11434/api/tags  # Liste des modèles
curl -X POST http://localhost:11434/api/generate -d '{"model":"mistral","prompt":"test"}'
curl -X POST http://localhost:11434/api/embeddings -d '{"model":"qwen3-embedding:8b","prompt":"test"}'

# Tester PostgreSQL
psql -h localhost -U docflow -d docflow

# Lancer le projet
docker compose up -d
```

---

## Prochaine étape

**Post-v1.3.0 :** validation déploiement production (docker compose up end-to-end), ivfflat tuning pgvector une fois les premières données chargées. Toute la couverture de tests est complète — 100% des routers backend et hooks frontend sont couverts.

## Commandes rapides

```bash
make help          # Liste toutes les cibles Makefile
make up            # Démarre tous les services
make test          # Lance backend + frontend tests
make test-e2e-mocked  # Tests E2E sans backend réel
make migrate       # Applique les migrations Alembic
make health        # Vérifie l'état des services
```
