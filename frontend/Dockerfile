# ============================================================
# DocFlow AI — Frontend Dockerfile (production)
# Build multi-stage : Node pour builder, Nginx pour servir
# AUCUNE donnée dans l'image, uniquement les assets statiques
# ============================================================

# --- Étape 1 : Build ---
FROM node:26-alpine AS builder

WORKDIR /app

# Dépendances
COPY package.json package-lock.json ./
RUN npm ci --prefer-offline

# Variables d'environnement de build (injectées via --build-arg)
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL

# Code source
COPY . .
RUN npm run build

# --- Étape 2 : Serveur Nginx ---
FROM nginx:alpine AS production

# Config Nginx (SPA : toutes les routes → index.html)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Assets buildés
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
