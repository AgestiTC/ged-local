# Documentation — DocFlow AI

Bienvenue dans la documentation de **DocFlow AI**, plateforme locale de gestion documentaire intelligente.

## Structure de la documentation

```
documentation/
├── README.md              ← Ce fichier (point d'entrée)
├── architecture.md        ← Architecture globale + flux de données
├── api-reference.md       ← Référence des endpoints API
├── database-schema.md     ← Schéma PostgreSQL + explication des tables
├── deployment.md          ← Guide de déploiement Docker
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
```

## Principe de documentation

**Cette documentation est évolutive** : chaque module est documenté au fur et à mesure de son implémentation.

Convention :
- `TODO Phase N` → section à rédiger lors de la Phase N
- Les sections existantes sont à jour avec le code

## Versions

| Version | Date | Contenu |
|---------|------|---------|
| v0.1.0 | 2026-04-10 | Scaffold initial, structure de la documentation |
| v0.2.0 | — | Phase 1 : backend + DB |
| v0.3.0 | — | Phase 2 : frontend + rapports |
| v1.0.0 | — | Stable, documentation complète |
