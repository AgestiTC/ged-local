# Guide de déploiement — DocFlow AI

> Ce guide couvre le déploiement **local (PC Windows/Linux)**.
> Pour un déploiement sur **Synology NAS**, voir [synology-deployment.md](synology-deployment.md).

## Prérequis

### Sur la machine hôte (déjà installé)

| Service | Version | URL par défaut | Rôle |
|---------|---------|----------------|------|
| Docker Desktop | 24+ | — | Conteneurisation |
| Ollama | latest | `http://localhost:11434` | Serveur LLM local |
| Apache Tika | latest | `http://localhost:9998` | Extraction documentaire |
| n8n | latest | `http://localhost:5678` | Orchestration workflows |

### Modèles Ollama requis

```bash
# Modèle principal (rapports, raisonnement)
ollama pull mixtral:latest

# Modèle rapide (tâches légères)
ollama pull mistral:latest

# Embeddings (recherche sémantique) — vérifier la dimension au 1er test
ollama pull qwen3-embedding:8b

# Fallback embeddings
ollama pull nomic-embed-text:latest
```

---

## Déploiement initial

### 1 — Cloner le dépôt

```bash
git clone https://git.agesti.fr/tclement/docflow.git
cd docflow
```

### 2 — Initialiser le projet

```bash
make setup
```

Cette commande :
- Crée `.env` depuis `.env.example`
- Crée tous les dossiers de stockage (`storage/`, `data/`, `logs/`)

### 3 — Configurer l'environnement

Édite `.env` et adapte **au minimum** ces variables :

```bash
# Mot de passe PostgreSQL (obligatoire — changer impérativement)
DB_PASSWORD=un_mot_de_passe_fort

# Dossier racine des documents à surveiller (chemin absolu sur l'hôte)
DOCUMENTS_ROOT=C:/Users/tclement/Documents

# Si Tika tourne déjà sur l'hôte (pas dans Docker)
TIKA_URL=http://host.docker.internal:9998
```

> Si Tika tourne **déjà** sur l'hôte, commenter le bloc `tika:` dans `docker-compose.yml`
> et garder `TIKA_URL=http://host.docker.internal:9998`.

### 4 — Démarrer les services

```bash
make up
```

Vérifie que les conteneurs démarrent :

```bash
make logs
# Ctrl+C pour quitter les logs
```

### 5 — Appliquer les migrations

```bash
make migrate
```

> La base de données est initialisée par `scripts/init-db.sql` au premier démarrage,
> puis les migrations Alembic prennent le relais pour les évolutions de schéma.

### 6 — Vérifier l'état des services

```bash
make health
```

Résultat attendu :
```
▶ État des services
Backend : ✓   (http://localhost:8000)
Tika    : ✓   (http://localhost:9998)
Ollama  : ✓   (http://localhost:11434)
```

### 7 — Accéder à l'application

| Interface | URL |
|-----------|-----|
| Frontend (app) | http://localhost:3001 |
| Backend API | http://localhost:8000 |
| Documentation API (Swagger) | http://localhost:8000/docs |
| Documentation API (ReDoc) | http://localhost:8000/redoc |

---

## Structure des dossiers de stockage

Tous les données sont sur l'hôte — **jamais dans les conteneurs** :

```
docflow/
├── data/postgres/          → données PostgreSQL (bind mount)
├── storage/
│   ├── uploads/            → fichiers uploadés via l'interface
│   ├── exports/            → rapports générés (PDF, DOCX)
│   ├── templates/          → templates DOCX/PDF pour remplissage
│   ├── documents/          → dossier source optionnel (si DOCUMENTS_ROOT non défini)
│   └── tika-config/        → configuration Tika (optionnel)
└── logs/                   → logs de tous les services
```

> Ces dossiers survivent à `docker compose down` — les données ne sont jamais perdues.

---

## Commandes de gestion courantes

```bash
# Cycle de vie
make up              # Démarrer tous les services
make down            # Arrêter (données conservées)
make restart         # Redémarrer sans rebuild
make logs            # Logs en temps réel
make logs-backend    # Logs backend uniquement

# Base de données
make migrate                        # Appliquer les migrations
make migrate-create MSG="ajout col" # Créer une nouvelle migration
make migrate-history                # Voir l'historique
make migrate-downgrade              # Annuler la dernière migration
make shell-db                       # Console psql

# Tests
make test                # Backend + frontend
make test-backend        # pytest uniquement
make test-frontend       # vitest uniquement
make test-e2e-mocked     # E2E sans backend réel

# Qualité
make lint                # Ruff + ESLint
make format              # Ruff format
make typecheck           # TypeScript

# Git
make push                # git push vers Gitea
make git-status          # État du dépôt

# Nettoyage
make clean               # Cache, dist, rapports de tests
make clean-docker        # Supprime les volumes Docker (⚠ perd les données)
```

---

## Mise à jour du projet

```bash
git pull
make build    # Rebuild les images si les Dockerfiles ont changé
make migrate  # Appliquer les nouvelles migrations
make restart  # Redémarrer avec les nouvelles images
```

---

## pgvector — Optimisation après les premiers données

L'index IVFFlat pour les embeddings doit être créé **après** avoir inséré des données
(nécessite au moins quelques centaines de vecteurs pour être efficace) :

```sql
-- Se connecter à la DB : make shell-db
-- Créer l'index une fois les premiers documents indexés
CREATE INDEX idx_embeddings_vector
    ON embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

> Adapter `lists` au volume : règle empirique = `sqrt(nombre_de_vecteurs)`.
> Exemple : 10 000 vecteurs → `lists = 100`, 100 000 vecteurs → `lists = 316`.

---

## Vérifier la dimension des embeddings qwen3-embedding:8b

Au premier démarrage, vérifier que la dimension retournée correspond au schéma (`4096`) :

```bash
curl -X POST http://localhost:11434/api/embeddings \
  -d '{"model":"qwen3-embedding:8b","prompt":"test"}' | python -m json.tool
```

Si la dimension retournée est différente de 4096, mettre à jour :
- `EMBEDDING_DIMENSION` dans `.env`
- La colonne `embedding vector(XXXX)` dans la migration Alembic
- L'init SQL `scripts/init-db.sql`

---

## Dépannage

### Le backend ne démarre pas

```bash
make logs-backend
# Vérifier DATABASE_URL dans .env
# Vérifier que postgres est healthy : docker compose ps
```

### Tika inaccessible

```bash
# Si Tika est dans Docker
docker compose ps tika
# Si Tika est sur l'hôte
curl http://localhost:9998/tika
```

### Ollama inaccessible depuis le backend

```bash
# Vérifier que host.docker.internal est résolu
docker compose exec backend curl http://host.docker.internal:11434/api/tags
```

### Réinitialiser complètement (⚠ supprime toutes les données)

```bash
make clean-docker          # Supprime les volumes Docker
rm -rf data/postgres/*     # Supprime les données PostgreSQL
rm -rf storage/uploads/*   # Supprime les fichiers uploadés
make up && make migrate    # Repart de zéro
```
