---
name: verify
description: Vérifier une modification de Matothèque dans l'appli qui tourne — pile jetable (Postgres éphémère + backend du code de la branche + Vite hôte), sans toucher à la base de dev ni à la prod.
---

# Vérifier Matothèque en conditions réelles

**Ne pas utiliser `docker-compose.dev.yml`** pour vérifier : il monte `./data/postgres`, la base de
dev qui sert aussi de source aux restaurations prod. Une vérification y laisserait ses essais.
**Jamais la prod** (`192.168.42.83`) : la simulation des congés, par exemple, écrit en base.

## Pile jetable (≈ 1 min, aucun build)

L'image backend publiée contient toutes les dépendances ; on y monte le code de la branche.

```bash
cd <repo>
docker network create verif
MSYS_NO_PATHCONV=1 docker run -d --name verif-pg --network verif --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_DB=docflow -e POSTGRES_USER=docflow -e POSTGRES_PASSWORD=dev \
  -v "$(pwd -W)/scripts/init-db.sql:/docker-entrypoint-initdb.d/01-init.sql:ro" pgvector/pgvector:pg16
# attendre : docker exec verif-pg pg_isready -U docflow -d docflow
MSYS_NO_PATHCONV=1 docker run -d --name verif-api --network verif -p 18000:8000 \
  -e DATABASE_URL=postgresql+asyncpg://docflow:dev@verif-pg:5432/docflow -e RUN_WORKER=false \
  -e TIKA_URL=http://none:9998 -e OLLAMA_URL=http://none:11434 \
  -v "$(pwd -W)/backend:/app" -w /app --entrypoint uvicorn \
  git.agesti.fr/agestitc/docflow-backend:latest main:app --host 0.0.0.0 --port 8000
# attendre : curl -sf localhost:18000/api/version
cd frontend && VITE_API_TARGET=http://localhost:18000 npx vite --port 5199 --strictPort   # en arrière-plan
```

UI : `http://localhost:5199` — piloter avec le MCP chrome-devtools (snapshot → fill/click → screenshot).

## Données minimales utiles

- Dossier « Devenir parent » + congés : `POST /api/dossiers {"titre":"Devenir parent"}`,
  `PATCH /api/dossiers/devenir-parent {"modules":{"conges":true}}` (sans ça, pas de bouton
  « Congés de naissance »), `PUT /api/system/config {"parents_date_terme":"2027-02-10"}`.
  Puis onglet **Planning** → **Congés de naissance**.

## Pièges

- **Windows : `TaskStop` sur `npx vite` laisse le `node` enfant** → port 5199 occupé au lancement
  suivant. Libérer : `Stop-Process -Id (Get-NetTCPConnection -LocalPort 5199 -State Listen).OwningProcess`.
- Les champs date du panneau sont `defaultValue` + `onBlur` : les remplir par script (setter natif
  + événement `input`, puis `blur()`) — c'est ce qui a marché ; les `<select>` se pilotent par `fill`.
- Tika / Ollama / ClamAV absents : pastilles rouges en haut, normal — sans effet hors indexation/IA.
- **⚠️ Plusieurs sessions Claude utilisent cette recette EN MÊME TEMPS** (constaté le 28/09) :
  avec les noms `verif-*` et le port 18000 fixes, une session a démarré son worker sur la base
  jetable d'une AUTRE. Préfixer TOUT par un tag propre à la tâche (`verif-h3-pg`,
  `verif-h3-api`, réseau `verif-h3`, port 18100…) ; au ménage, ne retirer QUE ce préfixe ; si
  `docker network create` échoue (« already exists »), s'ARRÊTER — c'est la pile d'un autre.
- **Vérifier le multi-process** (état en base vs en mémoire) : API en
  `uvicorn … --workers 2` + worker séparé (`--entrypoint python … worker.py`, même image, même
  `DATABASE_URL`, `RUN_WORKER=false` côté API) — c'est la topologie de la prod.
- **Port 5199 partagé avec NetSight** (autre projet, écoute en IPv6 `::1`) : `localhost:5199`
  peut ouvrir NetSight. Viser **`http://127.0.0.1:5199`**. Au ménage, n'arrêter que le process
  dont la ligne de commande contient `GED-LOCAL`.
- **`curl` sous Git Bash encode mal les accents** d'un `--data-urlencode` (« Impôts » → 0
  résultat trompeur). Encoder à la main : `categorie=Imp%C3%B4ts`.
- **Suite pytest dans le conteneur : ajouter `--tmpfs /app/storage:uid=10001`**. Le dossier
  hôte `backend/storage` (vide, ignoré par git) n'est pas inscriptible par l'uid 10001 →
  `test_secret_vide_est_conserve` échoue sur `.secret.key` sans que le code soit en cause.
- **Comparer avant/après sur la même base** : lancer en parallèle l'image publiée SANS montage
  (`-p 18001:8000 git.agesti.fr/agestitc/docflow-backend:<version prod>`) — c'est l'ancien code.

## Ménage

```bash
docker rm -f verif-api verif-pg && docker network rm verif
```
