# Documentation — DocFlow AI

Bienvenue dans la documentation de **DocFlow AI**, plateforme locale de gestion documentaire intelligente.

## Structure de la documentation

```
documentation/              ← Documentation technique et guides utilisateur
├── README.md              ← Ce fichier (point d'entrée)
├── architecture.md        ← Architecture globale + flux de données
├── api-reference.md       ← Référence des endpoints API
├── database-schema.md     ← Schéma PostgreSQL + explication des tables
├── modules/
│   ├── backend-overview.md      ← Vue d'ensemble du backend FastAPI
│   ├── tika-service.md          ← Module extraction Tika
│   ├── ollama-service.md        ← Module LLM + embeddings Ollama
│   ├── extraction-pipeline.md   ← Pipeline complet fichier → DB
│   ├── search-service.md        ← Recherche hybride full-text + sémantique
│   └── frontend-overview.md     ← Vue d'ensemble du frontend React
└── guides/
    ├── getting-started.md    ← Démarrage rapide
    ├── adding-documents.md   ← Ajouter des documents
    └── creating-reports.md   ← Créer un rapport

docs/                       ← Documentation opérationnelle (DevOps)
├── deployment.md           ← Déploiement Docker local (PC), dépannage, pgvector
├── synology-deployment.md  ← Déploiement sur Synology NAS (DSM 7 / Container Manager)
└── gitea-push.md           ← Configuration Git + push Gitea, tokens
```

## Principe de documentation

**Cette documentation est évolutive** : chaque module est documenté au fur et à mesure de son implémentation.

Convention :
- `TODO Phase N` → section à rédiger lors de la Phase N
- Les sections existantes sont à jour avec le code

## Versions

| Version | Date       | Contenu |
|---------|------------|---------|
| v0.1.0  | 2026-04-10 | Scaffold initial, structure de la documentation |
| v0.2.0  | 2026-04-13 | Backend complet : routers, services, migrations Alembic |
| v0.3.0  | 2026-04-13 | Frontend complet : composants, stores, hooks, pages |
| v1.0.0  | 2026-04-13 | Production-ready : Makefile, pagination GED, CI Gitea Actions |
| v1.3.0  | 2026-04-13 | Couverture de tests complète (180+ tests backend + frontend) |
| v1.4.0  | 2026-04-14 | Guide déploiement Synology NAS + fix Dockerfile weasyprint/libmagic |
