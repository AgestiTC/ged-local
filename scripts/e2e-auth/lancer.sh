#!/usr/bin/env bash
# Banc de bout en bout de l'authentification (étape 6, docs/plan-authentification.md).
# Pile JETABLE, préfixe propre (sessions concurrentes) : PostgreSQL éphémère, SSO simulé en HTTPS,
# backend du code de la branche (2 processus, comme la prod), VRAI nginx du frontend publié, puis
# le parcours « navigateur ». Termine par la sortie de secours `outils.auth --eteindre`.
# Ne touche ni la base de dev ni la prod. Usage (Git Bash, depuis la racine du dépôt) :
#   bash scripts/e2e-auth/lancer.sh            # tout, puis ménage
#   GARDER=1 bash scripts/e2e-auth/lancer.sh   # laisse la pile en place pour inspection
set -euo pipefail
export MSYS_NO_PATHCONV=1

P=${PREFIXE:-verif-e6}
IMG_BACK=${IMG_BACK:-git.agesti.fr/agestitc/docflow-backend:latest}
IMG_FRONT=${IMG_FRONT:-git.agesti.fr/agestitc/docflow-frontend:latest}
RACINE=$(cd "$(dirname "$0")/../.." && pwd -W 2>/dev/null || pwd)
BASE_URL="postgresql+asyncpg://docflow:e2e@$P-pg:5432/docflow"

menage() {
  [ "${GARDER:-0}" = "1" ] && { echo "Pile conservée (préfixe $P)."; return; }
  docker rm -f "$P-client" "$P-front" "$P-api" "$P-idp" "$P-pg" >/dev/null 2>&1 || true
  docker volume rm "$P-certs" >/dev/null 2>&1 || true
  docker network rm "$P" >/dev/null 2>&1 || true
}
attendre() {   # attendre <description> <commande…>
  local quoi=$1; shift
  for _ in $(seq 1 60); do "$@" >/dev/null 2>&1 && return 0; sleep 1; done
  echo "[ÉCHEC] $quoi : délai dépassé"; exit 1
}

# Réseau propre à CE banc : s'il existe déjà, c'est la pile d'un autre — on s'arrête.
docker network create "$P" >/dev/null || { echo "Réseau $P déjà présent : pile d'une autre session ?"; exit 1; }
trap menage EXIT
docker volume create "$P-certs" >/dev/null

docker run -d --name "$P-pg" --network "$P" --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_DB=docflow -e POSTGRES_USER=docflow -e POSTGRES_PASSWORD=e2e \
  -v "$RACINE/scripts/init-db.sql:/docker-entrypoint-initdb.d/01-init.sql:ro" pgvector/pgvector:pg16 >/dev/null

docker run -d --name "$P-idp" --network "$P" --network-alias idp --user 0 -v "$P-certs:/certs" \
  -v "$RACINE/scripts/e2e-auth:/e2e:ro" -w /e2e --entrypoint python "$IMG_BACK" idp_simule.py >/dev/null
attendre "certificat du SSO simulé" docker exec "$P-idp" test -s /certs/idp.pem
attendre "PostgreSQL" docker exec "$P-pg" pg_isready -U docflow -d docflow -h 127.0.0.1

# Backend : confiance au certificat du SSO simulé (ajouté au magasin de certifi), 2 processus.
docker run -d --name "$P-api" --network "$P" --network-alias backend --user 0 \
  -e DATABASE_URL="$BASE_URL" -e RUN_WORKER=false -e TIKA_URL=http://none:9998 -e OLLAMA_URL=http://none:11434 \
  -e CORS_ORIGINS="https://ged.test,http://front" --tmpfs /app/storage \
  -v "$P-certs:/certs:ro" -v "$RACINE/backend:/app" -w /app --entrypoint sh "$IMG_BACK" -c \
  'cat /certs/idp.pem >> "$(python -c "import certifi; print(certifi.where())")" && exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2' >/dev/null
attendre "backend" docker exec "$P-api" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/version')"

# Document fictif (le parcours lance un rapport dessus).
DOC_ID=$(docker exec "$P-pg" psql -U docflow -d docflow -tAq -c \
  "INSERT INTO documents (chemin, nom, extension, hash_sha256, texte_extrait, statut, source)
   VALUES ('/app/documents/e2e.pdf','e2e.pdf','pdf','e2e','Texte fictif.','enriched','upload') RETURNING id" | head -1)

docker run -d --name "$P-front" --network "$P" --network-alias front "$IMG_FRONT" >/dev/null
attendre "frontend (nginx)" docker exec "$P-front" wget -qO- http://127.0.0.1/api/version

echo "== Parcours =="
docker run --rm --name "$P-client" --network "$P" -e DOC_ID="$DOC_ID" -e FRONT=http://front \
  -v "$RACINE/scripts/e2e-auth:/e2e:ro" -w /e2e --entrypoint python "$IMG_BACK" -W ignore parcours.py

echo "== Sortie de secours : python -m outils.auth --eteindre (sur le serveur) =="
docker exec "$P-api" python -m outils.auth --eteindre
attendre "porte rouverte après --eteindre" docker exec "$P-front" sh -c \
  'test "$(wget -S -qO /dev/null http://127.0.0.1/api/documents 2>&1 | grep -c "HTTP/1.1 200")" -ge 1'
echo "[OK] --eteindre : l'API répond de nouveau sans session (la prod ne reste jamais verrouillée)."
echo "BANC VERT."
