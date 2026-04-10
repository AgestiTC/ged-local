# Guide de déploiement — DocFlow AI

## Prérequis

Sur la machine hôte (déjà installés) :
- Docker Desktop (Windows) avec WSL2
- Ollama avec les modèles requis
- Apache Tika (ou laisser Docker le gérer)
- n8n (optionnel pour la surveillance de dossiers)

## Premier démarrage

### 1. Configurer l'environnement

```bash
# Copier le fichier de configuration
cp .env.example .env

# Éditer .env et adapter :
# - DB_PASSWORD (mot de passe fort)
# - DOCUMENTS_ROOT (chemin vers vos documents)
# - OLLAMA_URL (si différent de localhost:11434)
```

### 2. Démarrer les services

```bash
# Production
docker compose up -d

# Développement (hot-reload backend)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### 3. Vérifier l'état

```bash
# État des conteneurs
docker compose ps

# Logs en temps réel
docker compose logs -f backend

# Logs PostgreSQL
docker compose logs postgres

# Test API
curl http://localhost:8000/health
```

### 4. Accéder à l'interface

- **Frontend** : http://localhost:3001
- **API Docs** : http://localhost:8000/api/docs
- **API ReDoc** : http://localhost:8000/api/redoc

## Arrêt et redémarrage

```bash
# Arrêter sans supprimer les données (les volumes hôte sont préservés)
docker compose down

# Reconstruire une image après modification du code
docker compose build backend
docker compose up -d backend

# Reconstruire tout
docker compose build
docker compose up -d
```

## Où sont les données ?

| Données | Dossier hôte | Description |
|---------|-------------|-------------|
| Base de données | `./data/postgres/` | Données PostgreSQL complètes |
| Fichiers uploadés | `./storage/uploads/` | Documents déposés via l'interface |
| Rapports générés | `./storage/exports/` | PDF et DOCX générés |
| Templates | `./storage/templates/` | Templates DOCX/PDF |
| Logs | `./logs/` | Logs applicatifs JSON |

> **Important** : Pour sauvegarder, copier ces dossiers. Pour migrer, copier ces dossiers vers la nouvelle machine.

## Sauvegarde PostgreSQL

```bash
# Dump complet
docker compose exec postgres pg_dump -U docflow docflow > backup_$(date +%Y%m%d).sql

# Restaurer
docker compose exec -T postgres psql -U docflow docflow < backup_20260410.sql
```

## Gitea — Pousser vers le dépôt local

```bash
# Ajouter le remote Gitea (adapter l'URL)
git remote add origin http://localhost:3000/user/docflow-ai.git

# Premier push
git push -u origin main
git push origin --tags
```

## Mise à jour du projet

```bash
# Récupérer les dernières modifications
git pull origin main

# Reconstruire si Dockerfile a changé
docker compose build

# Redémarrer
docker compose up -d
```

## Résolution de problèmes

### Ollama non accessible depuis Docker

```bash
# Vérifier que host.docker.internal résout
docker compose exec backend curl http://host.docker.internal:11434/api/tags
```

### PostgreSQL ne démarre pas

```bash
# Vérifier les permissions du dossier
ls -la ./data/postgres/

# Nettoyer et recommencer (EFFACE TOUTES LES DONNÉES)
docker compose down
rm -rf ./data/postgres/*
docker compose up -d
```

### Dimension d'embeddings incorrecte

Si `qwen3-embedding:8b` ne retourne pas des vecteurs de dimension 4096 :
```bash
# Tester la dimension réelle
curl -X POST http://localhost:11434/api/embeddings \
  -d '{"model":"qwen3-embedding:8b","prompt":"test"}' | jq '.embedding | length'

# Adapter dans .env
EMBEDDING_DIMENSION=<dimension_réelle>

# Adapter dans scripts/init-db.sql :
# embedding vector(<dimension_réelle>)
```
