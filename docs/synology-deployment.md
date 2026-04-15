# Déploiement sur Synology NAS — DocFlow AI

## Vue d'ensemble

```
┌─────────────────────┐   git push    ┌──────────────────────┐
│   PC Windows (dev)  │ ────────────► │   Gitea              │
│                     │               │                      │
│  ● Ollama :11434    │               │  CI → build images   │
│  ● n8n    :5678     │               │  Registry :          │
└─────────────────────┘               │  docflow-backend     │
         │                            │  docflow-frontend    │
         │ build manuel               └──────────┬───────────┘
         │ (première fois)                       │ docker pull (auto)
         └──────────────────────────────────────►│
                                      ┌──────────▼───────────┐
                                      │   Synology NAS        │
                                      │                      │
                                      │  ● PostgreSQL        │
                                      │  ● Tika              │
                                      │  ● Backend   :8000   │
                                      │  ● Frontend  :3001   │
                                      └──────────────────────┘
```

**Principe :**
- Le NAS utilise uniquement des images pré-buildées — **aucune compilation sur le NAS**
- La première fois : build manuel depuis le PC Windows
- Ensuite : Gitea Actions rebuild automatiquement à chaque `git push`

---

## Prérequis

### Sur le Synology NAS
- **DSM 7.0+** avec **Container Manager** installé (Package Center)
- Au moins **2 GB de RAM libre**

### Sur le PC Windows
- **Docker Desktop** installé et en cours d'exécution
- **Ollama** avec `OLLAMA_HOST=0.0.0.0` (voir [Étape 1](#étape-1--autoriser-ollama-sur-le-réseau))
- Modèles Ollama téléchargés :
  ```powershell
  ollama pull mixtral:latest
  ollama pull mistral:latest
  ollama pull qwen3-embedding:8b
  ollama pull nomic-embed-text:latest
  ```

### Sur Gitea
- **Packages activés** : Admin → Paramètres du site → Packages → Activer
- **Actions activées** : Admin → Paramètres du site → Actions → Activer *(pour les builds automatiques futurs)*
- Un **runner Gitea Actions** configuré *(optionnel au démarrage, voir [Annexe](#annexe--runner-gitea-actions-builds-automatiques))*

---

## Étape 1 — Autoriser Ollama sur le réseau (PC Windows)

Par défaut Ollama écoute uniquement sur `localhost`. Le NAS ne peut pas l'atteindre.

1. **Paramètres système avancés** → Variables d'environnement → Variables système → **Nouvelle** :
   - Nom : `OLLAMA_HOST`
   - Valeur : `0.0.0.0`
2. Quitter et relancer Ollama (icône systray → Quitter, puis relancer)
3. Si Windows Defender bloque : Pare-feu → Nouvelle règle entrante → Port TCP `11434`

**Vérification depuis le NAS** (Container Manager → Terminal) :
```bash
curl http://192.168.1.XXX:11434/api/tags   # IP du PC Windows
```

---

## Étape 2 — Builder et pousser les images (PC Windows)

Cette étape remplace le CI tant qu'un runner n'est pas configuré.
Ouvrir **PowerShell** dans le dossier du projet :

```powershell
# Authentification sur le registry Gitea
docker login git.agesti.fr
# Username : tclement
# Password : token Gitea → Settings → Applications → scope write:packages

# Backend
docker build -t git.agesti.fr/tclement/docflow-backend:latest ./backend
docker push git.agesti.fr/tclement/docflow-backend:latest

# Frontend (VITE_API_URL="" → nginx proxie /api/ vers backend, pas d'IP baked)
docker build --build-arg VITE_API_URL="" -t git.agesti.fr/tclement/docflow-frontend:latest ./frontend
docker push git.agesti.fr/tclement/docflow-frontend:latest
```

> **Note build frontend :** si `npm run build` échoue localement, lancer d'abord :
> ```powershell
> cd frontend && npm install && cd ..
> ```

---

## Étape 3 — Rendre les packages publics dans Gitea

Après le premier push, les images sont privées par défaut.

Dans Gitea → **Packages** → `docflow-backend` → **Paramètres** → Visibilité : **Public**
Répéter pour `docflow-frontend`.

→ Le NAS peut tirer les images **sans authentification**.

---

## Étape 4 — Ajouter le registry Gitea dans Container Manager

> ⚠️ **Étape obligatoire** — Container Manager doit connaître le registry Gitea avec vos credentials. Sans cette étape, toutes les images échouent avec `unauthorized: authentication required`.

**Générer un token Gitea** : Gitea → avatar → **Paramètres** → **Applications** → **Générer un token** :
- Nom : `nas-pull`
- Scope : `read:package`
- Copier le token généré

**Container Manager** → **Registre** (menu gauche) → **Ajouter** :

| Champ | Valeur |
|-------|--------|
| Nom | `Gitea` |
| URL | `https://git.agesti.fr` |
| Identifiant | `tclement` |
| Mot de passe | *(token Gitea généré ci-dessus)* |

Cliquer **Confirmer**.

---

## Étape 5 — Préparer les dossiers sur le NAS

Via **File Station** → dossier partagé `docker` → créer `docflow/` avec cette arborescence :

```
docker/docflow/
├── data/
│   └── postgres/
├── storage/
│   ├── uploads/
│   ├── exports/
│   └── templates/
└── logs/
```

---

## Étape 6 — Déposer les fichiers de configuration sur le NAS

Via **File Station** → `docker/docflow/` → déposer :

| Fichier | Où le trouver |
|---------|--------------|
| `docker-compose.nas.yml` | Racine du projet |
| `.env.nas.example` | Racine du projet |
| `scripts/init-db.sql` | Dossier `scripts/` |

---

## Étape 7 — Créer le fichier `.env`

Via **File Station** → copier `.env.nas.example` → renommer en `.env` → ouvrir avec l'éditeur de texte DSM.

Remplir les **3 variables obligatoires** :

```bash
DB_PASSWORD=un_mot_de_passe_fort        # ← choisir

OLLAMA_URL=http://192.168.1.42:11434    # ← IP du PC Windows (ipconfig → IPv4)

DOCUMENTS_ROOT=/volume1/documents       # ← chemin vers vos documents sur le NAS
```

> Docker Compose charge `.env` automatiquement — aucun flag `--env-file` nécessaire.

---

## Étape 8 — Démarrer les services

**Container Manager** → **Projet** → **Créer** :
- **Nom** : `docflow`
- **Chemin** : `/volume1/docker/docflow`
- **Fichier compose** : `docker-compose.nas.yml`
- Cliquer **Suivant** → **Terminer**

Les 4 conteneurs doivent passer au vert : `postgres` → `tika` → `backend` → `frontend`.

---

## Étape 9 — Migrations (première fois uniquement)

**Container Manager** → `docflow_backend` → **Terminal** :

```bash
alembic upgrade head
```

---

## Étape 10 — Accéder à l'application

| Interface | URL |
|-----------|-----|
| Application | `http://IP-DU-NAS:3001` |
| API / Swagger | `http://IP-DU-NAS:8000/docs` |

---

## Mise à jour

### Avec le CI configuré (runner Gitea Actions)
```
git push  →  CI build images  →  Container Manager → Mettre à jour → Démarrer
```

### Sans runner (build manuel depuis le PC)
```powershell
docker build -t git.agesti.fr/tclement/docflow-backend:latest ./backend
docker push git.agesti.fr/tclement/docflow-backend:latest
docker build --build-arg VITE_API_URL="" -t git.agesti.fr/tclement/docflow-frontend:latest ./frontend
docker push git.agesti.fr/tclement/docflow-frontend:latest
```
Puis sur le NAS : **Container Manager** → **Projet** → `docflow` → **Arrêter** → **Mettre à jour** → **Démarrer**.

Si une migration est nécessaire : Terminal `docflow_backend` → `alembic upgrade head`.

---

## Démarrage automatique au boot du NAS

**Container Manager** → Paramètres → Cocher **"Démarrer Docker au démarrage du système"**.
Les conteneurs ont `restart: unless-stopped` — ils redémarrent automatiquement.

---

## Dépannage

### Erreur de pull image — `Head "https://git.agesti.fr/v2/..."` (toutes les images)

```
Error response from daemon: Head "https://git.agesti.fr/v2/tclement/docflow-frontend/manifests/latest"
```
→ Le registry Gitea n'est pas enregistré dans Container Manager.
Faire l'**[Étape 4](#étape-4--ajouter-le-registry-gitea-dans-container-manager)**, puis relancer le projet.

### Erreur de pull image — `unauthorized`

```
Error response from daemon: unauthorized
```
→ Le package Gitea n'est pas public. Gitea → Packages → `docflow-backend` → Paramètres → Visibilité : Public.

### Erreur de pull image — `manifest unknown`

```
Error response from daemon: manifest unknown
```
→ L'image n'a jamais été poussée. Refaire l'[Étape 2](#étape-2--builder-et-pousser-les-images-pc-windows).

### Erreur de démarrage — `driver failed programming external connectivity`

```
Error response from daemon: driver failed programming external connectivity on endpoint docflow_postgres
Exit Code: 1
```
→ Un port est déjà utilisé sur le NAS. Le plus fréquent : le port `5432` (PostgreSQL DSM ou autre service).

Le service postgres n'a **pas besoin** d'être exposé à l'extérieur — le backend l'atteint via le réseau Docker interne. Le `docker-compose.nas.yml` ne publie pas ce port, ce problème ne devrait donc pas se produire.

Si vous voyez cette erreur sur un autre port, modifier la variable correspondante dans `.env` :
```bash
FRONTEND_PORT=3002    # si 3001 est occupé
BACKEND_PORT=8001     # si 8000 est occupé
```

### `DB_PASSWORD variable is not set`

→ Le fichier `.env` est absent ou mal placé. Il doit être dans le même dossier que `docker-compose.nas.yml` (`/volume1/docker/docflow/.env`).

### Ollama inaccessible depuis le backend

```bash
# Terminal conteneur backend
curl http://192.168.1.XXX:11434/api/tags
```
→ Vérifier `OLLAMA_HOST=0.0.0.0` sur le PC + redémarrage Ollama + règle pare-feu Windows port 11434.

### Le backend ne démarre pas

**Container Manager** → `docflow_backend` → **Journal** :
- `password authentication failed` → vérifier `DB_PASSWORD` dans `.env`
- `connection refused` vers postgres → attendre que `docflow_postgres` soit `healthy`

### Erreur de permissions sur les volumes

```bash
# SSH sur le NAS
chmod -R 755 /volume1/docker/docflow/storage/
chmod -R 755 /volume1/docker/docflow/logs/
chmod 700 /volume1/docker/docflow/data/postgres/
```

### Réinitialiser complètement (⚠ supprime toutes les données)

1. **Container Manager** → **Projet** → `docflow` → **Arrêter**
2. **File Station** → Vider `data/postgres/` et `storage/uploads/`
3. **Démarrer** le projet
4. Terminal `docflow_backend` → `alembic upgrade head`

---

## Annexe — Runner Gitea Actions (builds automatiques)

Une fois le runner configuré, chaque `git push` sur `main` ou tag `vX.Y.Z` déclenche automatiquement le build et le push des images. Plus besoin de builder depuis le PC.

**Démarrer un runner sur le NAS via SSH :**

```bash
# Récupérer le token : Gitea → dépôt → Paramètres → Actions → Exécuteurs → Créer
docker run -d \
  --name gitea-runner \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /volume1/docker/gitea-runner:/data \
  -e GITEA_INSTANCE_URL=https://git.agesti.fr \
  -e GITEA_RUNNER_REGISTRATION_TOKEN=TOKEN_ICI \
  gitea/act_runner:latest
```

Une fois actif, le workflow `.gitea/workflows/build-push.yml` s'exécute automatiquement.

---

## Annexe — Optimisation pgvector

Après indexation des premiers documents, créer l'index vectoriel.
**Container Manager** → `docflow_postgres` → **Terminal** :

```sql
-- Adapter lists = sqrt(nombre_de_vecteurs)
-- 10 000 documents → lists = 100
CREATE INDEX CONCURRENTLY idx_embeddings_vector
    ON embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```
