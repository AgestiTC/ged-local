# Module Backend — Vue d'ensemble

## FastAPI — Point d'entrée

**Fichier** : [backend/main.py](../../backend/main.py)

Configure l'application FastAPI, les middlewares CORS, et monte tous les routers.
Le logging est initialisé ici avant tout import.

## Configuration

**Fichier** : [backend/config.py](../../backend/config.py)

Singleton `Settings` (pydantic-settings) qui lit toutes les variables depuis `.env`.
Importez avec :
```python
from config import get_settings
settings = get_settings()
```

## Logging

**Fichier** : [backend/logger.py](../../backend/logger.py)

Logging structuré JSON via `structlog`. Format JSON en production, console colorée en dev.

```python
from logger import get_logger
log = get_logger(__name__)
log.info("événement", document_id=doc_id, statut="extracted")
```

## Modules

| Dossier | Rôle |
|---------|------|
| `models/` | Modèles SQLAlchemy (tables DB) |
| `services/` | Logique métier (Tika, Ollama, recherche...) |
| `routers/` | Routes FastAPI (endpoints HTTP) |
| `utils/` | Fonctions utilitaires (hash, chunker, fichiers) |
| `alembic/` | Migrations de base de données |

## Modèles (tables DB)

| Fichier | Table | Rôle |
|---------|-------|------|
| `document.py` | `documents` | Fichiers indexés |
| `metadata.py` | `metadonnees_ia` | Enrichissement LLM |
| `embedding.py` | `embeddings` | Vecteurs pgvector |
| `version.py` | `versions` | Historique fichiers |
| `template.py` | `templates` | Templates DOCX/PDF |
| `job.py` | `jobs` | File d'attente |
| `prompt.py` | `prompts_presets` | Prompts sauvegardés |
| `folder.py` | `dossiers_surveilles` | Dossiers à scanner |

## Services

| Fichier | Rôle | Phase |
|---------|------|-------|
| `tika_service.py` | Client Tika (extraction) | Phase 1 |
| `ollama_service.py` | Client Ollama (LLM + embeddings) | Phase 1 |
| `extraction.py` | Pipeline extraction complet | Phase 1 |
| `embedding_service.py` | Génération + stockage vecteurs | Phase 1 |
| `report_generator.py` | Construction contexte + génération | Phase 2 |
| `export_service.py` | Export PDF + DOCX | Phase 2 |
| `template_filler.py` | Remplissage templates DOCX | Phase 2 |
| `search_service.py` | Recherche hybride | Phase 3 |
| `ged_service.py` | CRUD documents GED | Phase 3 |
| `folder_watcher.py` | Surveillance dossiers (fallback n8n) | Phase 1 |

## TODO Phase 1

- [ ] Connexion asyncpg + pool de connexions SQLAlchemy
- [ ] Migrations Alembic (créer la première migration depuis les modèles)
- [ ] Implémenter `ExtractionService.process_file()`
- [ ] Implémenter `TikaService` (déjà codé, tester)
- [ ] Implémenter `OllamaService` (déjà codé, tester)
- [ ] Endpoints `/api/upload`, `/api/extract`, `/api/documents`
- [ ] Health check avec test de connectivité réel
