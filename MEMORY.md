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

## État d'avancement

### ✅ Fait
- [x] Spécifications complètes (CLAUDE.md)
- [x] Schéma de base de données défini
- [x] Architecture et API endpoints définis
- [x] Structure de fichiers du projet définie

### 🔲 Phase 1 — Fondation
- [ ] docker-compose.yml (PostgreSQL/pgvector + backend + frontend + Tika)
- [ ] Backend FastAPI : squelette + config
- [ ] Modèles SQLAlchemy + migrations Alembic
- [ ] Service Tika : client async + tests par format
- [ ] Service Ollama : client LLM + client embeddings
- [ ] Pipeline extraction complet
- [ ] API upload (multipart, drag & drop)
- [ ] Workflow n8n : surveillance dossiers

### 🔲 Phase 2 — Interface & Rapports
- [ ] Setup React + Vite + Tailwind
- [ ] DropZone (drag & drop fichiers/dossiers/ZIP)
- [ ] Navigateur fichiers (arborescence + sélection)
- [ ] Éditeur de prompt + presets + sélecteur modèle
- [ ] Génération rapports (streaming SSE)
- [ ] Prévisualisation + export PDF/DOCX
- [ ] Templates (upload + remplissage)

### 🔲 Phase 3 — GED
- [ ] Recherche hybride (full-text + vectorielle)
- [ ] Interface GED (recherche + filtres + grille)
- [ ] Fiche document + métadonnées éditables
- [ ] Classification automatique
- [ ] Versioning
- [ ] Déduplication

### 🔲 Phase 4 — Polish
- [ ] Page paramètres
- [ ] Gestion d'erreurs robuste
- [ ] Tests
- [ ] Documentation utilisateur

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

**Commencer par la Phase 1, étape 1 :** créer le `docker-compose.yml` et le squelette FastAPI avec les modèles de base de données.
