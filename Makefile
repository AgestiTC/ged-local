# Makefile — DocFlow AI
# =====================
# Commandes de développement courantes.
# Utilisation : make <cible>

.PHONY: help up down logs build \
        test test-backend test-frontend test-e2e test-e2e-ui \
        migrate migrate-create lint format \
        seed clean reset

# ── Couleurs ─────────────────────────────────────────────────────────────────
BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[32m
BLUE  := \033[34m

# ── Variables ─────────────────────────────────────────────────────────────────
COMPOSE := docker compose
BACKEND := $(COMPOSE) exec backend
FRONTEND_DIR := frontend

# ─────────────────────────────────────────────────────────────────────────────

help: ## Affiche cette aide
	@echo ""
	@echo "$(BOLD)DocFlow AI — Commandes disponibles$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ── Cycle de vie Docker ───────────────────────────────────────────────────────

up: ## Démarre tous les services (docker compose up -d)
	$(COMPOSE) up -d
	@echo "$(GREEN)✓ Services démarrés$(RESET)"
	@echo "  Frontend : http://localhost:3001"
	@echo "  Backend  : http://localhost:8000"
	@echo "  API docs : http://localhost:8000/docs"

down: ## Arrête tous les services
	$(COMPOSE) down

logs: ## Affiche les logs en temps réel
	$(COMPOSE) logs -f

logs-backend: ## Affiche les logs du backend uniquement
	$(COMPOSE) logs -f backend

logs-frontend: ## Affiche les logs du frontend uniquement
	$(COMPOSE) logs -f frontend

build: ## Rebuild les images Docker
	$(COMPOSE) build

restart: ## Redémarre les services sans rebuild
	$(COMPOSE) restart

# ── Tests ─────────────────────────────────────────────────────────────────────

test: test-backend test-frontend ## Lance tous les tests (backend + frontend)

test-backend: ## Lance les tests pytest (backend)
	@echo "$(BLUE)▶ Tests backend$(RESET)"
	cd backend && python -m pytest tests/ -v --tb=short

test-frontend: ## Lance les tests vitest (frontend)
	@echo "$(BLUE)▶ Tests frontend$(RESET)"
	cd $(FRONTEND_DIR) && npm run test

test-frontend-coverage: ## Lance vitest avec rapport de couverture
	cd $(FRONTEND_DIR) && npm run test -- --coverage

test-e2e: ## Lance les tests E2E Playwright (nécessite le serveur dev)
	@echo "$(BLUE)▶ Tests E2E$(RESET)"
	cd $(FRONTEND_DIR) && npm run test:e2e

test-e2e-ui: ## Lance Playwright en mode UI interactif
	cd $(FRONTEND_DIR) && npm run test:e2e:ui

test-e2e-mocked: ## Lance uniquement les tests E2E mockés (sans backend)
	cd $(FRONTEND_DIR) && npx playwright test e2e/mocked/ --reporter=list

# ── Base de données ───────────────────────────────────────────────────────────

migrate: ## Applique les migrations Alembic en attente
	@echo "$(BLUE)▶ Migration base de données$(RESET)"
	$(BACKEND) alembic upgrade head

migrate-create: ## Crée une nouvelle migration (usage: make migrate-create MSG="description")
	@if [ -z "$(MSG)" ]; then \
		echo "Erreur : fournir un message avec MSG=\"description\""; \
		exit 1; \
	fi
	$(BACKEND) alembic revision --autogenerate -m "$(MSG)"

migrate-history: ## Affiche l'historique des migrations
	$(BACKEND) alembic history --verbose

migrate-current: ## Affiche la migration courante
	$(BACKEND) alembic current

migrate-downgrade: ## Annule la dernière migration
	$(BACKEND) alembic downgrade -1

# ── Développement ─────────────────────────────────────────────────────────────

dev-backend: ## Lance le backend FastAPI en mode développement (hot reload)
	cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Lance le serveur de développement Vite
	cd $(FRONTEND_DIR) && npm run dev

install: ## Installe les dépendances (backend + frontend)
	cd backend && pip install -r requirements.txt
	cd $(FRONTEND_DIR) && npm install

install-playwright: ## Installe les navigateurs Playwright
	cd $(FRONTEND_DIR) && npx playwright install chromium

# ── Qualité de code ───────────────────────────────────────────────────────────

lint: lint-backend lint-frontend ## Lance tous les linters

lint-backend: ## Lint Python avec ruff
	cd backend && python -m ruff check .

lint-frontend: ## Lint TypeScript avec ESLint
	cd $(FRONTEND_DIR) && npm run lint

format: format-backend ## Formate le code

format-backend: ## Formate Python avec ruff
	cd backend && python -m ruff format .

typecheck: ## Vérifie les types TypeScript
	cd $(FRONTEND_DIR) && npm run typecheck

# ── Utilitaires ───────────────────────────────────────────────────────────────

seed: ## Insère les prompts pré-enregistrés par défaut
	$(BACKEND) python -c "import asyncio; from main import _seed_prompts_defaut; from database import AsyncSessionLocal; asyncio.run(lambda: None())"

shell-backend: ## Ouvre un shell dans le conteneur backend
	$(BACKEND) bash

shell-db: ## Ouvre psql dans le conteneur PostgreSQL
	$(COMPOSE) exec postgres psql -U docflow -d docflow

health: ## Vérifie l'état de tous les services
	@echo "$(BLUE)▶ État des services$(RESET)"
	@curl -sf http://localhost:8000/health | python -m json.tool || echo "Backend : ❌"
	@curl -sf http://localhost:9998/tika | grep -q "Apache Tika" && echo "Tika    : ✓" || echo "Tika    : ❌"
	@curl -sf http://localhost:11434/api/tags | python -m json.tool > /dev/null && echo "Ollama  : ✓" || echo "Ollama  : ❌"

# ── Nettoyage ─────────────────────────────────────────────────────────────────

clean: ## Supprime les fichiers temporaires et caches
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -name "*.pyc" -delete 2>/dev/null || true
	rm -rf $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/coverage
	rm -rf $(FRONTEND_DIR)/playwright-report $(FRONTEND_DIR)/test-results

clean-docker: ## Supprime les volumes Docker (⚠ perd les données)
	$(COMPOSE) down -v

reset: clean ## Réinitialise l'environnement de développement (sans données)
	$(COMPOSE) down
	$(MAKE) up
	sleep 5
	$(MAKE) migrate
	@echo "$(GREEN)✓ Environnement réinitialisé$(RESET)"

# ── Documentation ─────────────────────────────────────────────────────────────

docs-serve: ## Sert la documentation locale avec mkdocs (si installé)
	mkdocs serve

.DEFAULT_GOAL := help
