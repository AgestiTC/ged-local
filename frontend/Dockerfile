# ============================================================
# DocFlow AI — Frontend Dockerfile (production)
# Build multi-stage : Node pour builder, Nginx pour servir
# AUCUNE donnée dans l'image, uniquement les assets statiques
# ============================================================

# --- Étape 1 : Build ---
FROM node:20-alpine AS builder

WORKDIR /app

# Dépendances
COPY package.json package-lock.json ./
RUN npm ci --prefer-offline

# Variables d'environnement de build (injectées via --build-arg).
# ⚠️ Défaut = VIDE → l'apiClient utilise des URLs RELATIVES (/api) servies par le
# nginx du frontend (production derrière reverse-proxy). NE PAS remettre
# http://localhost:8000 ici : ça figerait l'API sur la machine du navigateur et
# casserait toute la prod (voyants rouges, pas de version, « Impossible de charger »).
# Pour un build pointant vers un backend distant explicite : --build-arg VITE_API_URL=https://…
ARG VITE_API_URL=
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
