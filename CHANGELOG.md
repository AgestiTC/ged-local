# Changelog — DocFlow AI

Toutes les modifications notables de ce projet sont documentées ici.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/)
Versioning : [Semantic Versioning](https://semver.org/lang/fr/)

---

## [Unreleased]

### En cours
- Phase 1 — Fondation : backend FastAPI + PostgreSQL/pgvector + Tika + Ollama

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

| Version | Contenu | Phase |
|---------|---------|-------|
| `v0.1.0` | Scaffold + structure | — |
| `v0.2.0` | Backend complet (Tika + Ollama + DB) | Phase 1 |
| `v0.3.0` | Frontend + génération de rapports | Phase 2 |
| `v0.4.0` | GED : recherche hybride + interface | Phase 3 |
| `v1.0.0` | Stable, testé, documenté | Phase 4 |
