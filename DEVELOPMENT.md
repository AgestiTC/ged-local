# DEVELOPMENT.md — Matothèque

> **Principe fondateur — développer SANS reconstruire d'image Docker à chaque
> changement.** Le code est rechargé **à chaud** ; on ne (re)build une image que
> lorsqu'une **dépendance** change (`backend/requirements.txt`, `frontend/package.json`).

---

## Stack

| Composant | Techno | Port dev |
|---|---|---|
| Backend | FastAPI (Python 3.11) + SQLAlchemy async | 8000 |
| Frontend | React 18 + TypeScript + Vite + Tailwind | 3001 (Vite) |
| Base | PostgreSQL 16 + pgvector | 5432 |
| Extraction | Apache Tika | 9998 |
| LLM / Embeddings | Ollama (sur l'hôte) | 11434 |

Services externes (Ollama, n8n) tournent **sur l'hôte**, hors Docker.

---

## A. Lancer l'environnement de dev (à chaud, sans rebuild)

### Option A — Bare-metal (la plus rapide)

Seul **Postgres** (+ Tika) tourne en conteneur ; backend et frontend en local.

```bash
# 1. La base (et Tika si pas déjà sur l'hôte)
docker compose up -d postgres tika

# 2. Backend — reload à chaud sur chaque .py
cd backend
python -m venv .venv && . .venv/Scripts/activate   # 1re fois (Windows : .venv\Scripts\Activate.ps1)
pip install -r requirements.txt                    # 1re fois / si requirements change
uvicorn main:app --reload --port 8000

# 3. Frontend — HMR Vite sur chaque .tsx
cd frontend
npm install                                        # 1re fois / si package.json change
npm run dev                                         # proxy /api → :8000
```

Chaque save `.py` → `uvicorn --reload` recharge ; chaque save `.tsx` → HMR Vite. **Aucun rebuild.**

> Pour pointer le backend local vers le Postgres conteneurisé, exporter
> `DATABASE_URL=postgresql+asyncpg://docflow:<pwd>@localhost:5432/docflow`
> (le `<pwd>` = `DB_PASSWORD` de ton `.env`).

### Option B — Tout en conteneurs (recommandé — pattern NetSight)

Stack dev **autonome** : aucun outil requis sur l'hôte (ni Python, ni Node).
Chaque composant a son `Dockerfile.dev` (dépendances seulement) ; le code est
monté en volume.

```bash
docker compose -f docker-compose.dev.yml up
#   UI  : http://localhost:5174     ·     API : http://localhost:8000/docs
```

- Save `.py` → `uvicorn --reload` ; save `.tsx` → HMR Vite. **Aucun rebuild d'image.**
- `node_modules` reste celui de l'image (volume anonyme) → pas de `npm install` sur l'hôte.
- Le proxy `/api` de Vite vise le **service** `backend` via `VITE_API_TARGET=http://backend:8000`.
- **Ports choisis pour coexister avec NetSight** (qui occupe 5173/5432/8090) :
  UI `5174`, API `8000` ; **postgres et tika n'exposent aucun port hôte** (accès interne).
- La prod reste l'image multi-stage non-root (`docker-compose.yml`).

### Quand faut-il rebuild une image dev ?

| Je change…                          | Rebuild image ?                                              |
|-------------------------------------|-------------------------------------------------------------|
| code Python (`backend/`)            | ❌ non — `uvicorn --reload`                                  |
| une vue / un asset (`frontend/`)    | ❌ non — HMR Vite                                            |
| `backend/requirements.txt`          | ✅ `docker compose -f docker-compose.dev.yml build backend`  |
| `frontend/package.json`             | ✅ `docker compose -f docker-compose.dev.yml build frontend` |
| `Dockerfile` / `Dockerfile.dev`     | ✅ rebuild du service concerné                               |

---

## Tests (comme la CI)

```bash
# Backend — pytest + SQLite in-memory (pas de Postgres requis)
cd backend && pytest -q

# Frontend — vitest + e2e Playwright
cd frontend && npm test
npm run test:e2e          # (si configuré)
```

La CI (`.github/workflows/ci.yml`) rejoue ces commandes : un test vert en local
doit l'être en CI (pas de dépendance cachée à un service externe).

---

## Versionnage & release

- **Source de vérité unique** : fichier `VERSION` à la racine, lu par `config.py`
  (→ endpoint `/api/version`) et injecté dans l'image via `--build-arg APP_VERSION`
  (sans lui, l'UI affiche « vdev »).
- Release : `./scripts/release.ps1 -Version X.Y.Z -Message "..."` (bump + commit +
  tag annoté + push sur `origin`). **Le tag ne construit aucune image** : le workflow GHCR
  de `.github/` est un vestige. Pousser aussi sur Gitea : `git push gitea main --follow-tags`.
- ⚠️ Si tu bumpes `VERSION` **à la main** (hors `release.ps1`), pense à
  `frontend/package.json` : le script synchronise les deux, pas toi.
- Voir aussi `CLAUDE.md` (Git Flow : `feature/*` → `develop` → `main`).

## Déployer en prod

**Merger n'est pas déployer.** Le registre réel est **Gitea** (`git.agesti.fr/agestitc/docflow-*`),
le build+push se fait **depuis Windows**, et la prod (LXC « docker », `192.168.42.83`,
`/opt/docflow`) ne tire rien toute seule. Une seule commande fait tout :

```powershell
.\scripts\deployer.ps1                    # build (X.Y.Z + latest) + push + LXC + vérification
.\scripts\deployer.ps1 -SansCache         # si un build échoue sur des « Invalid character »
.\scripts\verifier-deploiement.ps1        # le seul verdict : registre, latest = ce build, prod servie
```

Le script fait aussi `docker compose restart frontend` sur le LXC (sinon nginx garde l'ancienne
IP du backend). **Ne jamais l'appeler avec `2>&1`** (PowerShell 5.1 transforme la sortie d'erreur
de `docker login`/`git push` en échec). Prérequis : Docker Desktop lancé, et aucune tâche en cours
en prod (un `up -d` interromprait une analyse).

**Règle de travail** : une livraison est terminée quand la prod la sert — sinon dire
explicitement que la prod est en retard. Lister les étapes applicatives éventuelles (migration,
seed à rejouer, réglage à saisir). Procédure complète et pièges : `CLAUDE.md` § Déploiement.
