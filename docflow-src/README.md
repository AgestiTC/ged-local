# DocFlow AI

Plateforme locale de gestion documentaire intelligente — **100% local, aucun cloud**.

Deux modules intégrés :
- **DocFlow Reports** — génération automatique de rapports à partir de documents via IA locale
- **DocFlow GED** — gestion électronique de documents avec recherche sémantique

---

## Fonctionnalités

### DocFlow Reports
- Glisser-déposer de fichiers, dossiers entiers ou archives ZIP
- Éditeur de prompt avec presets pré-enregistrés
- Choix du modèle Ollama (Mixtral, Mistral, LLaMA…)
- 3 modes de sortie : rapport libre, remplissage de template DOCX/PDF, classement/tri
- Streaming SSE — le rapport s'affiche mot par mot
- Export PDF et DOCX

### DocFlow GED
- Indexation automatique des dossiers surveillés
- Recherche hybride : full-text (PostgreSQL) + sémantique (pgvector)
- Classification automatique par IA (catégorie, tags, résumé, entités)
- Détection de doublons par hash SHA256
- Historique des versions avec diff résumé par IA
- Pagination avec chargement progressif

### Formats supportés
PDF · DOCX · PPTX · PPSX · XLSX · ZIP · ODT · ODS · ODP

---

## Stack technique

| Couche | Technologie |
|--------|-------------|
| Backend | FastAPI (Python 3.11+, async) |
| Base de données | PostgreSQL 16 + pgvector |
| Frontend | React 18 + TypeScript + Vite + TailwindCSS |
| État global | Zustand |
| Extraction documentaire | Apache Tika |
| LLM & embeddings | Ollama (Mixtral, qwen3-embedding:8b…) |
| Migrations | Alembic |
| Conteneurisation | Docker Compose |
| Orchestration | n8n |

---

## Prérequis

Sur la machine hôte (à installer avant) :

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) 24+
- [Ollama](https://ollama.com/) avec les modèles requis
- [Apache Tika](https://tika.apache.org/) (serveur sur le port 9998)
- [n8n](https://n8n.io/) (optionnel — surveillance automatique de dossiers)

```bash
# Modèles Ollama requis
ollama pull mixtral:latest
ollama pull mistral:latest
ollama pull qwen3-embedding:8b
ollama pull nomic-embed-text:latest
```

---

## Démarrage rapide

```bash
# 1. Cloner
git clone https://git.agesti.fr/tclement/docflow.git
cd docflow

# 2. Initialiser (crée .env + dossiers de stockage)
make setup

# 3. Configurer — éditer .env
#    Obligatoire : DB_PASSWORD, DOCUMENTS_ROOT
nano .env

# 4. Démarrer
make up

# 5. Appliquer les migrations
make migrate

# 6. Vérifier
make health
```

L'application est disponible sur :
- **Frontend** → http://localhost:3001
- **API** → http://localhost:8000
- **Swagger** → http://localhost:8000/docs

---

## Commandes principales

```bash
make help              # Liste toutes les commandes disponibles

# Cycle de vie
make up                # Démarrer les services
make down              # Arrêter
make logs              # Logs en temps réel
make health            # État de tous les services

# Tests
make test              # Backend (pytest) + Frontend (vitest)
make test-e2e-mocked   # Tests E2E sans backend

# Base de données
make migrate           # Appliquer les migrations
make shell-db          # Console PostgreSQL

# Développement local (sans Docker)
make dev-backend       # FastAPI avec hot reload
make dev-frontend      # Vite dev server

# Qualité
make lint              # Ruff + ESLint
make typecheck         # TypeScript
```

---

## Architecture

```
┌─────────────────────────────────────────┐
│         Frontend React (port 3001)      │
│  Reports · GED · Settings               │
└──────────────────┬──────────────────────┘
                   │ REST API / SSE
         ┌─────────▼─────────┐
         │   FastAPI Backend  │
         │   (port 8000)      │
         └──┬──────┬──────┬──┘
            │      │      │
       ┌────▼─┐ ┌──▼──┐ ┌─▼──────────┐
       │ Tika │ │Olla-│ │ PostgreSQL  │
       │ 9998 │ │ ma  │ │ + pgvector  │
       │      │ │11434│ │             │
       └──────┘ └─────┘ └────────────┘
```

---

## Structure du projet

```
docflow/
├── backend/            API FastAPI
│   ├── routers/        Endpoints REST
│   ├── services/       Logique métier (Tika, Ollama, extraction…)
│   ├── models/         Modèles SQLAlchemy
│   ├── alembic/        Migrations de base de données
│   └── tests/          Tests pytest (100+ tests)
├── frontend/           Interface React
│   ├── src/
│   │   ├── components/ Composants UI
│   │   ├── pages/      Pages principales
│   │   ├── stores/     État global Zustand
│   │   ├── hooks/      Hooks React
│   │   └── __tests__/  Tests Vitest (80+ tests)
│   └── e2e/            Tests Playwright
├── n8n/workflows/      Automatisation (surveillance dossiers, indexation)
├── scripts/            Init SQL + seed prompts
├── storage/            Fichiers runtime (uploads, exports, templates)
├── docs/               Documentation (déploiement, Gitea)
├── docker-compose.yml
├── Makefile
└── .env.example
```

---

## Tests

```bash
# Backend — pytest + SQLite in-memory
make test-backend

# Frontend — Vitest
make test-frontend

# E2E — Playwright (mockés, sans backend)
make test-e2e-mocked
```

Couverture :
- **Backend** : 14 fichiers de tests, 100+ tests — tous les routers et services
- **Frontend** : stores, hooks, utilitaires — 80+ tests
- **E2E** : navigation, rapports, GED, upload — 7 suites

---

## Documentation

- [Guide de déploiement](docs/deployment.md) — installation complète, dépannage
- [Configuration Gitea](docs/gitea-push.md) — push, tokens, workflow git
- [CHANGELOG](CHANGELOG.md) — historique des versions
- [CLAUDE.md](CLAUDE.md) — architecture détaillée et spécifications

---

## Licence

Usage interne — © 2026 Agesti
