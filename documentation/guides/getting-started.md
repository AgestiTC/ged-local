# Guide de démarrage — DocFlow AI

## Prérequis vérifiés

```bash
# Vérifier Ollama
curl http://localhost:11434/api/tags

# Vérifier Tika
curl http://localhost:9998/tika

# Vérifier Docker
docker --version
docker compose version
```

## Démarrage en 3 étapes

```bash
# 1. Configuration
cp .env.example .env
# Éditer .env : DB_PASSWORD et DOCUMENTS_ROOT

# 2. Lancer les services
docker compose up -d

# 3. Vérifier
curl http://localhost:8000/health
# Ouvrir http://localhost:3001
```

## Ajouter des documents

Voir [adding-documents.md](./adding-documents.md).

## Créer un rapport

Voir [creating-reports.md](./creating-reports.md).
