# Déploiement sur Synology NAS — DocFlow AI

## Vue d'ensemble

```
┌─────────────────────┐   git push    ┌──────────────────────┐
│   PC Windows (dev)  │ ────────────► │   Gitea              │
│                     │               │                      │
│  ● Ollama :11434    │               │  CI → build images   │
│  ● n8n    :5678     │               │  Registry :          │
└─────────────────────┘               │  docflow-backend     │
                                      │  docflow-frontend    │
                                      └──────────┬───────────┘
                                                 │ docker pull
                                      ┌──────────▼───────────┐
                                      │   Synology NAS        │
                                      │                      │
                                      │  ● PostgreSQL        │
                                      │  ● Tika              │
                                      │  ● Backend   :8000   │
                                      │  ● Frontend  :3001   │
                                      └──────────────────────┘
```

**Principe :** Gitea Actions construit les images Docker à chaque push sur `main` et les pousse sur le registry Gitea. Le NAS tire les images pré-buildées — **aucune compilation sur le NAS**.

---

## Prérequis

### Sur le Synology NAS
- **DSM 7.0+** avec **Container Manager** installé
- Au moins **2 GB de RAM libre** (images déjà compilées, pas de build)

### Sur le PC Windows
- **Ollama** en cours d'exécution avec `OLLAMA_HOST=0.0.0.0` (voir [Étape 1](#étape-1--autoriser-ollama-sur-le-réseau))
- Modèles Ollama déjà téléchargés :
  ```powershell
  ollama pull mixtral:latest
  ollama pull mistral:latest
  ollama pull qwen3-embedding:8b
  ollama pull nomic-embed-text:latest
  ```

### Sur Gitea (configuration unique, une seule fois)
- **Actions activées** : Admin → Paramètres du site → Actions → Activer
- **Packages activés** : Admin → Paramètres du site → Packages → Activer
- **Packages publics** : dans chaque image après le premier build →
  Gitea → **Packages** → `docflow-backend` → **Paramètres** → Visibilité : **Public**
  *(idem pour `docflow-frontend`)*
  → Le NAS peut tirer les images **sans aucun login**
- Un **runner Gitea Actions** disponible (voir [Configurer un runner](#annexe--configurer-un-runner-gitea-actions))

---

## Étape 1 — Autoriser Ollama sur le réseau

Par défaut Ollama n'écoute que sur `localhost`. Il faut l'ouvrir au réseau LAN pour que le NAS puisse l'atteindre.

1. **Paramètres système avancés** → Variables d'environnement → Variables système → **Nouvelle** :
   - Nom : `OLLAMA_HOST`
   - Valeur : `0.0.0.0`
2. Quitter et relancer Ollama (icône systray → Quitter, puis relancer)
3. Si Windows Defender bloque : Pare-feu → Nouvelle règle entrante → Port `11434`

**Vérification :** depuis le NAS (SSH ou terminal Container Manager) :
```bash
curl http://192.168.1.XXX:11434/api/tags   # remplacer par l'IP du PC
```

---

## Étape 2 — Vérifier que les images sont buildées

Après chaque `git push` sur `main` ou création d'un tag `vX.Y.Z`, Gitea Actions :
1. Lance les tests (ci.yml)
2. Build les images backend et frontend
3. Les pousse sur `git.agesti.fr/tclement/docflow-backend:latest` et `docflow-frontend:latest`

Vérifier dans Gitea : **Dépôt** → **Packages** → les deux images doivent apparaître.

> Si les images n'apparaissent pas : vérifier que Actions et Packages sont activés dans l'admin Gitea,
> et qu'un runner est disponible (onglet **Actions** → **Exécuteurs**).

---

## Étape 3 — Configurer les dossiers sur le NAS

Via **File Station** → créer l'arborescence dans le dossier partagé `docker` :

```
docker/docflow/
├── data/postgres/
└── storage/
    ├── uploads/
    ├── exports/
    └── templates/
└── logs/
```

---

## Étape 4 — Déposer les fichiers de configuration sur le NAS

Via **File Station**, déposer dans `docker/docflow/` les fichiers suivants
(télécharger depuis Gitea ou copier depuis le PC) :

| Fichier | Rôle |
|---------|------|
| `docker-compose.nas.yml` | Compose NAS (images registry) |
| `.env.nas.example` | Template de configuration |
| `scripts/init-db.sql` | Initialisation PostgreSQL |

---

## Étape 5 — Créer le fichier `.env`

Via **File Station** → copier `.env.nas.example` → renommer `.env` → ouvrir avec l'éditeur de texte DSM.

> Docker Compose charge `.env` automatiquement depuis le dossier du projet — aucun flag supplémentaire à passer.

Remplir les **3 variables obligatoires** :

```bash
DB_PASSWORD=un_mot_de_passe_fort        # ← choisir un mot de passe

OLLAMA_URL=http://192.168.1.42:11434    # ← IP du PC Windows (ipconfig → IPv4)

DOCUMENTS_ROOT=/volume1/documents       # ← chemin vers vos documents sur le NAS
```

Tout le reste a des valeurs par défaut correctes.

---

## Étape 6 — Démarrer les services

Via **Container Manager** → **Projet** → **Créer** :
- **Nom** : `docflow`
- **Chemin** : `/volume1/docker/docflow`
- **Fichier compose** : sélectionner `docker-compose.nas.yml`
- **Fichier env** : sélectionner `.env.nas`
- Cliquer **Suivant** → **Terminer**

Container Manager va tirer les images depuis Gitea puis démarrer les 4 services.
Le premier pull peut prendre quelques minutes selon la connexion.

---

## Étape 7 — Migrations (première fois uniquement)

Une fois les conteneurs démarrés, via **Container Manager** → `docflow_backend` → **Terminal** :

```bash
alembic upgrade head
```

---

## Étape 8 — Accéder à l'application

| Interface | URL |
|-----------|-----|
| Application | `http://IP-DU-NAS:3001` |
| API / Swagger | `http://IP-DU-NAS:8000/docs` |

---

## Mise à jour (workflow quotidien)

```
git push  →  Gitea Actions build + push  →  NAS pull + restart
```

Sur le NAS, via **Container Manager** → **Projet** → `docflow` :
1. **Arrêter**
2. **Mettre à jour** (tire les nouvelles images)
3. **Démarrer**
4. Si migration nécessaire : Terminal `docflow_backend` → `alembic upgrade head`

> Pour épingler une version précise : mettre `DOCFLOW_VERSION=v1.4.0` dans `.env.nas`
> puis **Arrêter** / **Démarrer** (pas besoin de rebuild).

---

## Dépannage

### Les images ne se téléchargent pas

```
Error: unauthorized
```
→ Refaire le `docker login git.agesti.fr` sur le NAS (token expiré ou manquant).

### Ollama inaccessible

```bash
# Terminal conteneur backend
curl http://192.168.1.XXX:11434/api/tags
```
→ Vérifier `OLLAMA_HOST=0.0.0.0` sur le PC + redémarrage Ollama + règle pare-feu Windows.

### Le backend ne démarre pas

**Container Manager** → `docflow_backend` → **Journal** :
- `password authentication failed` → vérifier `DB_PASSWORD` dans `.env.nas`
- `connection refused` vers postgres → attendre que `docflow_postgres` soit `healthy`

### Erreur de permissions volumes

```bash
# SSH sur le NAS
chmod -R 755 /volume1/docker/docflow/storage/
chmod -R 755 /volume1/docker/docflow/logs/
chmod 700 /volume1/docker/docflow/data/postgres/
```

---

## Annexe — Configurer un runner Gitea Actions

Le runner est nécessaire pour que les workflows CI/CD s'exécutent.

**Option A — Runner sur le NAS lui-même :**
```bash
# SSH sur le NAS
docker run -d \
  --name gitea-runner \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /volume1/docker/gitea-runner:/data \
  -e GITEA_INSTANCE_URL=https://git.agesti.fr \
  -e GITEA_RUNNER_REGISTRATION_TOKEN=TOKEN_ICI \
  gitea/act_runner:latest
```
Récupérer le token : Gitea → dépôt → **Paramètres** → **Actions** → **Exécuteurs** → **Créer un exécuteur**.

**Option B — Runner sur le PC Windows :**
Télécharger `act_runner` depuis [gitea.com/gitea/act_runner/releases](https://gitea.com/gitea/act_runner/releases) et l'enregistrer avec le token du dépôt.

---

## Annexe — Optimisation pgvector

Après indexation des premiers documents (quelques centaines), créer l'index vectoriel.
Via **Container Manager** → `docflow_postgres` → **Terminal** :

```sql
CREATE INDEX CONCURRENTLY idx_embeddings_vector
    ON embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
-- Adapter lists = sqrt(nombre_de_vecteurs)
```
