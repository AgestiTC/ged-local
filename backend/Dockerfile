# ============================================================
# DocFlow AI — Backend Dockerfile
# ============================================================
# Image de base Python 3.11 slim
# AUCUNE donnée applicative dans l'image : tout est monté via volumes
# ============================================================

FROM python:3.11-slim

# Métadonnées
LABEL maintainer="DocFlow AI"
LABEL description="Backend FastAPI — DocFlow AI"

# Variables d'environnement Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dépendances système
# - weasyprint : pango, cairo, gdk-pixbuf, libffi, fonts
# - python-magic : libmagic1
# - psycopg2 : libpq-dev
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    libmagic1 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Code source
COPY . .

# Créer les dossiers de stockage (ils seront montés depuis l'hôte)
# Ces dossiers ne contiendront jamais de données dans l'image
RUN mkdir -p /app/storage/uploads \
             /app/storage/exports \
             /app/storage/templates \
             /app/logs \
             /app/documents

# Port exposé
EXPOSE 8000

# Commande de démarrage (production)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
