# Déploiement sur Synology NAS — DocFlow AI

## Vue d'ensemble

Ce guide couvre le déploiement de DocFlow AI sur un **Synology NAS avec DSM 7** (Container Manager).

**Architecture cible :**

```
┌─────────────────────┐        ┌──────────────────────────────┐
│   PC Windows (LAN)  │        │   Synology NAS               │
│                     │        │                              │
│  ● Ollama :11434    │◄──────►│  ● PostgreSQL (Docker)       │
│  ● n8n    :5678     │        │  ● Tika       (Docker)       │
│                     │        │  ● Backend    (Docker) :8000 │
│                     │        │  ● Frontend   (Docker) :3001 │
└─────────────────────┘        └──────────────────────────────┘
                                         ▲
                                         │ http://IP-NAS:3001
                                    Navigateur
```

Le frontend appelle `/api/` en relatif → nginx du NAS proxie vers le backend → plus besoin d'IP baked dans le build.

---

## Prérequis

### Sur le Synology NAS

- **DSM 7.0+** avec **Container Manager** installé (Package Center)
- **SSH activé** (Panneau de configuration → Terminal & SNMP → SSH)
- Docker Compose v2 disponible via Container Manager
- Au moins **4 GB de RAM libre** sur le NAS (PostgreSQL + Tika + Backend + Frontend)

### Sur le PC Windows

- **Ollama** installé et en cours d'exécution
- **n8n** installé et en cours d'exécution (optionnel)
- Les modèles Ollama nécessaires déjà téléchargés :

```powershell
ollama pull mixtral:latest
ollama pull mistral:latest
ollama pull qwen3-embedding:8b
ollama pull nomic-embed-text:latest
```

### Réseau

- Le NAS et le PC Windows sont sur le **même réseau LAN**
- Connaître l'**IP locale du PC Windows** (`ipconfig` → IPv4 de la carte LAN, ex: `192.168.1.42`)
- Connaître l'**IP locale du NAS** (Panneau de configuration → Réseau, ou DSM → Informations)

---

## Étape 1 — Autoriser Ollama sur le réseau (PC Windows)

Par défaut, Ollama n'écoute que sur `localhost`. Il faut l'autoriser à accepter les connexions réseau depuis le NAS.

**Méthode : variable d'environnement système Windows**

1. Ouvrir **Paramètres système avancés** → Onglet Avancé → Variables d'environnement
2. Dans "Variables système", cliquer **Nouvelle** :
   - Nom : `OLLAMA_HOST`
   - Valeur : `0.0.0.0`
3. **Redémarrer le service Ollama** (quitter l'icône systray et relancer)

**Vérification depuis le NAS :**
```bash
# Depuis SSH sur le NAS, remplacer 192.168.1.42 par l'IP du PC
curl http://192.168.1.42:11434/api/tags
# Doit retourner la liste des modèles
```

> Si un pare-feu Windows bloque la connexion : Windows Defender Firewall → Autoriser une application → Ajouter une règle entrante pour le port 11434.

---

## Étape 2 — Préparer les dossiers sur le NAS

Via **File Station** (interface graphique DSM) :

1. Ouvrir **File Station**
2. Naviguer dans `docker` (dossier partagé Docker, créé automatiquement par Container Manager)
3. Créer le dossier `docflow` dans `docker/`
4. À l'intérieur de `docflow/`, créer la structure suivante :

```
docker/docflow/
├── data/
│   └── postgres/          ← données PostgreSQL
└── storage/
    ├── uploads/           ← fichiers uploadés via l'interface
    ├── exports/           ← rapports générés
    └── templates/         ← templates DOCX/PDF
└── logs/                  ← logs des services
```

> Si vos documents sont dans un dossier partagé existant sur le NAS (ex: `documents/`), vous n'avez pas besoin de le créer.

---

## Étape 3 — Déployer le code sur le NAS

Via **File Station** (interface graphique DSM) :

1. Sur le **PC Windows**, compresser le dossier du projet en ZIP (clic droit → Envoyer vers → Dossier compressé)
   - Exclure : `.git/`, `node_modules/`, `__pycache__/`, `data/`, `storage/`, `logs/`

2. Dans **File Station** → Naviguer dans `docker/docflow/`

3. Cliquer **Charger** (bouton en haut) → Sélectionner le ZIP

4. Clic droit sur le ZIP → **Extraire ici**

5. Vérifier que les fichiers sont bien présents :
   `docker-compose.yml`, `docker-compose.synology.yml`, `.env.synology.example`,
   dossiers `backend/`, `frontend/`, `scripts/`

> **Alternative :** Si votre Gitea est accessible depuis le NAS, vous pouvez aussi cloner
> via SSH : `git clone https://git.agesti.fr/tclement/docflow.git /volume1/docker/docflow`

---

## Étape 4 — Configurer l'environnement

Via **File Station** :

1. Dans `docker/docflow/`, trouver `.env.synology.example`
2. Clic droit → **Copier** → Coller dans le même dossier → Renommer en `.env.synology`
3. Double-clic sur `.env.synology` → **Éditeur de texte** DSM

Remplir les valeurs **obligatoires** :

```bash
# Mot de passe PostgreSQL — changer impérativement
DB_PASSWORD=un_mot_de_passe_fort_ici

# IP du PC Windows (où Ollama tourne)
# ipconfig sur le PC Windows → adresse IPv4 de la carte LAN
OLLAMA_URL=http://192.168.1.42:11434    # ← Remplacer par l'IP réelle du PC

# Dossier de documents à surveiller (chemin sur le NAS)
DOCUMENTS_ROOT=/volume1/documents       # ← Adapter si vos docs sont ailleurs
```

Sauvegarder le fichier.

---

## Étape 5 — Démarrer les services via Container Manager

1. Ouvrir **Container Manager** sur DSM

2. Aller dans **Projet** → **Créer**

3. Remplir le formulaire :
   - **Nom du projet** : `docflow`
   - **Chemin** : `/volume1/docker/docflow`
   - **Source** : "Utiliser docker-compose.yml du chemin du projet"

4. Dans le champ **docker-compose.yml**, entrer le contenu **fusionné** des deux fichiers.
   Voir la section [Fichier compose fusionné pour Container Manager](#fichier-compose-fusionné-pour-container-manager) ci-dessous.

5. Cliquer **Suivant** → **Terminer**

6. Container Manager va builder les images (~5-10 min) puis démarrer les services.

> Container Manager ne supporte pas nativement `docker compose -f ... -f ...` (fichiers multiples).
> C'est pourquoi on utilise un fichier fusionné à l'étape 5.

---

### Fichier compose fusionné pour Container Manager

Copier-coller ce contenu dans Container Manager (remplacer les valeurs en `← À CHANGER`) :

```yaml
services:

  postgres:
    image: pgvector/pgvector:pg16
    container_name: docflow_postgres
    restart: unless-stopped
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: docflow
      POSTGRES_USER: docflow
      POSTGRES_PASSWORD: "← MOT_DE_PASSE_ICI"   # ← À CHANGER
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - /volume1/docker/docflow/data/postgres:/var/lib/postgresql/data
      - /volume1/docker/docflow/scripts/init-db.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U docflow -d docflow"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - docflow_net

  tika:
    image: apache/tika:latest
    container_name: docflow_tika
    restart: unless-stopped
    ports:
      - "9998:9998"
    networks:
      - docflow_net

  backend:
    build:
      context: /volume1/docker/docflow/backend
      dockerfile: Dockerfile
    container_name: docflow_backend
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: "postgresql+asyncpg://docflow:← MOT_DE_PASSE_ICI@postgres:5432/docflow"
      TIKA_URL: http://tika:9998
      OLLAMA_URL: "http://192.168.1.XXX:11434"   # ← IP DU PC WINDOWS
      N8N_URL: "http://192.168.1.XXX:5678"        # ← IP DU PC WINDOWS
      OLLAMA_MODEL_DEFAULT: mixtral:latest
      OLLAMA_MODEL_FAST: mistral:latest
      OLLAMA_MODEL_EMBEDDING: qwen3-embedding:8b
      OLLAMA_MODEL_EMBEDDING_FALLBACK: nomic-embed-text:latest
      CHUNK_SIZE: "500"
      CHUNK_OVERLAP: "50"
      EMBEDDING_DIMENSION: "4096"
      OLLAMA_TIMEOUT_MS: "300000"
      TIKA_TIMEOUT_MS: "60000"
      LOG_LEVEL: INFO
      LOG_FORMAT: json
      LOG_FILE: /app/logs/docflow-backend.log
      DEBUG: "false"
    volumes:
      - /volume1/docker/docflow/storage/uploads:/app/storage/uploads
      - /volume1/docker/docflow/storage/exports:/app/storage/exports
      - /volume1/docker/docflow/storage/templates:/app/storage/templates
      - /volume1/docker/docflow/logs:/app/logs
      - /volume1/documents:/app/documents:ro    # ← Adapter si nécessaire
    depends_on:
      postgres:
        condition: service_healthy
      tika:
        condition: service_started
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks:
      - docflow_net

  frontend:
    build:
      context: /volume1/docker/docflow/frontend
      dockerfile: Dockerfile
      args:
        VITE_API_URL: ""
    container_name: docflow_frontend
    restart: unless-stopped
    ports:
      - "3001:80"
    depends_on:
      - backend
    networks:
      - docflow_net

networks:
  docflow_net:
    driver: bridge
    name: docflow_network
```

---

## Étape 6 — Appliquer les migrations

Une fois les conteneurs démarrés, via **Container Manager** :

1. Aller dans **Conteneur** → `docflow_backend`
2. Cliquer **Terminal** → **Créer** → **bash**
3. Dans le terminal :

```bash
alembic upgrade head
```

Ou depuis **SSH sur le NAS** :
```bash
docker exec docflow_backend alembic upgrade head
```

---

## Étape 7 — Vérifier l'état des services

Dans **Container Manager** → **Projet** → `docflow` : tous les conteneurs doivent être verts.

Depuis le navigateur :
```
http://IP-DU-NAS:8000/health   → {"status": "ok"}
http://IP-DU-NAS:3001          → Interface DocFlow AI
```

**Vérifier la connexion Ollama** via le terminal du conteneur backend :
```bash
curl http://192.168.1.XXX:11434/api/tags   # Remplacer par l'IP du PC
```

---

## Étape 8 — Accéder à l'application

| Interface | URL |
|-----------|-----|
| Application | `http://IP-DU-NAS:3001` |
| API Backend | `http://IP-DU-NAS:8000` |
| Swagger UI | `http://IP-DU-NAS:8000/docs` |

---

## Mise à jour du projet

1. Téléverser le nouveau ZIP via **File Station** → Extraire (écraser les fichiers existants)
2. Dans **Container Manager** → **Projet** → `docflow` → **Arrêter**
3. **Reconstruire** (rebuild des images)
4. **Démarrer**
5. Terminal `docflow_backend` → `alembic upgrade head`

---

## Démarrage automatique

Container Manager redémarre automatiquement les conteneurs avec `restart: unless-stopped`.

Pour s'assurer que Docker démarre au boot : **Container Manager** → Paramètres → Cocher **"Démarrer Docker au démarrage du système"**.

---

## Dépannage

### Ollama inaccessible depuis le backend

```bash
# Terminal du conteneur backend (Container Manager → docflow_backend → Terminal)
curl http://192.168.1.XXX:11434/api/tags

# Si timeout → vérifier OLLAMA_HOST=0.0.0.0 sur le PC Windows
# Si refus de connexion → vérifier le pare-feu Windows (port 11434)
```

### Le backend ne démarre pas

Dans **Container Manager** → **Conteneur** → `docflow_backend` → **Journal** :
- Erreur `DATABASE_URL` → vérifier `POSTGRES_PASSWORD` dans le compose
- Erreur `connection refused postgres` → attendre que postgres soit healthy (vérifier `docflow_postgres`)

### Erreur de permissions sur les volumes

```bash
# SSH sur le NAS
chmod -R 755 /volume1/docker/docflow/storage/
chmod -R 755 /volume1/docker/docflow/logs/
chmod 700 /volume1/docker/docflow/data/postgres/
```

### Vérifier la dimension des embeddings qwen3-embedding:8b

```bash
# Depuis le PC Windows (PowerShell)
curl -X POST http://localhost:11434/api/embeddings `
  -d '{"model":"qwen3-embedding:8b","prompt":"test"}'
# Compter les valeurs dans "embedding": [...]
# Si ≠ 4096 → mettre à jour EMBEDDING_DIMENSION dans le compose
```

### Réinitialiser complètement (⚠ supprime toutes les données)

1. **Container Manager** → **Projet** → `docflow` → **Arrêter**
2. **File Station** → Vider `docker/docflow/data/postgres/` et `docker/docflow/storage/uploads/`
3. **Container Manager** → **Projet** → `docflow` → **Démarrer**
4. Terminal backend → `alembic upgrade head`

---

## Optimisation pgvector (après premiers documents indexés)

Une fois les premières centaines de documents indexés, créer l'index IVFFlat via le terminal du conteneur `docflow_postgres` :

```sql
-- Adapter lists = sqrt(nombre_de_vecteurs)
-- ex: 10 000 vecteurs → lists = 100
CREATE INDEX CONCURRENTLY idx_embeddings_vector
    ON embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```
  -f docker-compose.yml \
  -f docker-compose.synology.yml \
  --env-file .env.synology \
  logs -f
```

**Vérifier que tous les conteneurs sont up :**
```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.synology.yml \
  --env-file .env.synology \
  ps
```

Résultat attendu :
```
NAME                 STATUS          PORTS
docflow_postgres     Up (healthy)    0.0.0.0:5432->5432/tcp
docflow_tika         Up              0.0.0.0:9998->9998/tcp
docflow_backend      Up              0.0.0.0:8000->8000/tcp
docflow_frontend     Up              0.0.0.0:3001->80/tcp
```

---

## Étape 6 — Appliquer les migrations

```bash
docker exec docflow_backend alembic upgrade head
```

---

## Étape 7 — Vérifier l'état des services

```bash
# Health check backend
curl http://IP-DU-NAS:8000/health

# Vérifier la connexion Ollama depuis le backend
docker exec docflow_backend curl http://IP-PC-WINDOWS:11434/api/tags

# Vérifier Tika
curl http://IP-DU-NAS:9998/tika
```

---

## Étape 8 — Accéder à l'application

| Interface | URL |
|-----------|-----|
| Application | `http://IP-DU-NAS:3001` |
| API Backend | `http://IP-DU-NAS:8000` |
| Swagger UI | `http://IP-DU-NAS:8000/docs` |

---

## Commandes de gestion courantes

Créer un alias pour simplifier les commandes (ajouter dans `~/.bashrc` sur le NAS) :

```bash
alias docflow='docker compose \
  -f /volume1/docker/docflow/docker-compose.yml \
  -f /volume1/docker/docflow/docker-compose.synology.yml \
  --env-file /volume1/docker/docflow/.env.synology'
```

Puis :
```bash
docflow up -d           # Démarrer
docflow down            # Arrêter (données conservées)
docflow logs -f         # Logs en temps réel
docflow ps              # État des conteneurs
docflow restart backend # Redémarrer un service
```

---

## Mise à jour du projet

1. Téléverser le nouveau ZIP via **File Station** → Extraire (écraser les fichiers existants)
2. **Container Manager** → **Projet** → `docflow` → **Arrêter**
3. **Reconstruire** (rebuild des images)
4. **Démarrer**
5. Terminal `docflow_backend` → `alembic upgrade head`

---

## Démarrage automatique

Container Manager sur DSM 7 redémarre automatiquement les conteneurs avec `restart: unless-stopped` (déjà configuré dans docker-compose.yml).

Pour s'assurer que Docker démarre au boot du NAS : **Container Manager** → Paramètres → Cocher "Démarrer Docker au démarrage du système".

---

## Dépannage

### Ollama inaccessible depuis le backend

```bash
# Tester depuis le conteneur backend
docker exec docflow_backend curl http://IP-PC-WINDOWS:11434/api/tags

# Si timeout : vérifier OLLAMA_HOST=0.0.0.0 sur le PC Windows
# Si refus de connexion : vérifier le pare-feu Windows (port 11434)
```

### Le backend ne démarre pas

```bash
docker logs docflow_backend --tail 50

# Erreur DATABASE_URL → vérifier DB_PASSWORD dans .env.synology
# Erreur "connection refused postgres" → attendre que postgres soit healthy
docker logs docflow_postgres --tail 20
```

### Frontend : "Cannot connect to API"

```bash
# Le proxy nginx redirige /api/ vers le backend
# Vérifier que le backend est up
docker logs docflow_frontend
docker exec docflow_frontend wget -qO- http://backend:8000/health
```

### Erreur de permissions sur les volumes

Via **SSH sur le NAS** :
```bash
chmod -R 755 /volume1/docker/docflow/storage/
chmod -R 755 /volume1/docker/docflow/logs/
chmod 700 /volume1/docker/docflow/data/postgres/
```

### Vérifier la dimension des embeddings qwen3-embedding:8b

```powershell
# Depuis le PC Windows (PowerShell)
curl -X POST http://localhost:11434/api/embeddings `
  -d '{"model":"qwen3-embedding:8b","prompt":"test"}'
# Compter les valeurs dans "embedding": [...]
# Si ≠ 4096 → mettre à jour EMBEDDING_DIMENSION dans le compose Container Manager
```

### Réinitialiser complètement (⚠ supprime toutes les données)

1. **Container Manager** → **Projet** → `docflow` → **Arrêter**
2. **File Station** → Vider `docker/docflow/data/postgres/` et `docker/docflow/storage/uploads/`
3. **Container Manager** → **Projet** → `docflow` → **Démarrer**
4. Terminal `docflow_backend` → `alembic upgrade head`

---

## Optimisation pgvector (après premiers documents indexés)

Une fois les premières centaines de documents indexés, créer l'index IVFFlat.

Via **Container Manager** → `docflow_postgres` → **Terminal** :

```sql
-- Adapter lists = sqrt(nombre_de_vecteurs)
-- ex: 10 000 vecteurs → lists = 100
CREATE INDEX CONCURRENTLY idx_embeddings_vector
    ON embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

