# Architecture — DocFlow AI

## Vue d'ensemble

DocFlow AI est une plateforme **100% locale** (zéro cloud) composée de :

1. **DocFlow Reports** — Génération de rapports via IA à partir de documents
2. **DocFlow GED** — Gestion Électronique de Documents avec recherche sémantique

## Principe Docker : données sur l'hôte

> **Règle fondamentale : AUCUNE donnée dans les conteneurs Docker.**

Tous les volumes sont des **bind mounts** vers des dossiers de l'hôte :

| Dossier hôte | Monté dans | Contenu |
|---|---|---|
| `./data/postgres/` | `/var/lib/postgresql/data` | Données PostgreSQL |
| `./storage/uploads/` | `/app/storage/uploads` | Fichiers uploadés |
| `./storage/exports/` | `/app/storage/exports` | Rapports générés |
| `./storage/templates/` | `/app/storage/templates` | Templates DOCX/PDF |
| `./logs/` | `/app/logs` | Logs applicatifs |
| `${DOCUMENTS_ROOT}` | `/app/documents` (ro) | Sources surveillées |

**Avantages** :
- Les conteneurs sont **jetables** et reconstruisibles sans perte de données
- Sauvegardes simples : copie des dossiers hôte
- Accès direct aux données sans passer par Docker

## Services

### Dans Docker

| Service | Image | Port | Rôle |
|---------|-------|------|------|
| `postgres` | pgvector/pgvector:pg16 | 5432 | Base de données |
| `tika` | apache/tika:latest | 9998 | Extraction documents |
| `backend` | ./backend (custom) | 8000 | API FastAPI |
| `frontend` | ./frontend (custom) | 3001 | Interface React |

### Sur l'hôte (non dockerisés)

| Service | Port | Rôle |
|---------|------|------|
| Ollama | 11434 | LLM + embeddings (GPU natif) |
| n8n | 5678 | Orchestration workflows |

> Ollama reste sur l'hôte pour accéder directement au GPU sans overhead Docker.

## Flux de données

```
Fichier détecté/uploadé
        ↓
    Hash SHA256
        ↓
  Doublon ? → Oui → Ignorer / mettre à jour
        ↓ Non
  DB : documents (statut=pending)
        ↓
  Tika → texte + métadonnées
        ↓
  DB : documents (statut=extracted)
        ↓
  Ollama (mistral) → catégorie/tags/résumé/entités (JSON)
        ↓
  DB : metadonnees_ia
        ↓
  Chunker → N chunks de 500 tokens
        ↓
  Ollama (qwen3-embedding:8b) × N → vecteurs 4096 dims
        ↓
  DB : embeddings (pgvector)
        ↓
  DB : documents (statut=enriched)
```

## Logging

- **Format** : JSON structuré (structlog) en production, console colorée en dev
- **Fichier** : `./logs/docflow-backend.log` (sur l'hôte via volume)
- **Niveaux** : DEBUG (dev), INFO (prod)
- **Champs** : timestamp, level, logger (module), event, + contexte métier

## Versioning Git

| Tag | Contenu |
|-----|---------|
| `v0.1.0` | Scaffold initial |
| `v0.2.0` | Phase 1 : backend complet |
| `v0.3.0` | Phase 2 : frontend + rapports |
| `v0.4.0` | Phase 3 : GED |
| `v1.0.0` | Stable production |
