# ============================================================
# DocFlow AI / Matothèque — Backend Dockerfile (multi-stage, non-root)
# ============================================================
# AUCUNE donnée applicative dans l'image : tout est monté via volumes.
# Conventions modèle docker AgestiTC : multi-stage + USER non-root + HEALTHCHECK.
# ============================================================

# ----------------------------------------------------------
# Stage 1 — builder : compile les dépendances Python dans un venv isolé
# ----------------------------------------------------------
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Dépendances de BUILD uniquement (compilation de wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ----------------------------------------------------------
# Stage 2 — runtime : image finale légère, non-root
# ----------------------------------------------------------
FROM python:3.14-slim AS runtime

LABEL maintainer="Matothèque (AgestiTC)"
LABEL description="Backend FastAPI — Matothèque (DocFlow AI)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"

# Version injectée au build par la CI (source de vérité : fichier VERSION racine).
# Lue par config.py via la variable d'env APP_VERSION → endpoint /api/version.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

# Dépendances de RUNTIME uniquement
# - weasyprint : pango, cairo, gdk-pixbuf, fonts
# - python-magic : libmagic1
# - psycopg : libpq5
# - curl : healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    libmagic1 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur non-root
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

# venv pré-construit depuis le builder
COPY --from=builder /opt/venv /opt/venv

# Code source
COPY . .

# Dossiers de stockage (montés depuis l'hôte au runtime), possédés par appuser
RUN mkdir -p /app/storage/uploads \
             /app/storage/exports \
             /app/storage/templates \
             /app/logs \
             /app/documents \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Healthcheck aligné sur le liveness probe /healthz
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
