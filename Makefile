# Makefile for fx-historical-market-analysis-service.
#
# The backend virtualenv and the frontend node_modules are expected to exist.
# Run `make setup` once to create them.

SHELL := /bin/bash
BACKEND_PY := backend/.venv/Scripts/python.exe
FRONTEND := frontend

.DEFAULT_GOAL := help
.PHONY: help setup setup-backend setup-frontend dev dev-backend dev-frontend \
        test test-backend test-frontend lint lint-backend lint-frontend \
        typecheck typecheck-backend typecheck-frontend build build-frontend \
        check check-backend check-frontend clean docker-build docker-up docker-down

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: setup-backend setup-frontend ## Install backend and frontend dependencies

setup-backend: ## Create the backend virtualenv and install dependencies
	python -m venv backend/.venv
	backend/.venv/Scripts/python.exe -m pip install --upgrade pip
	backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"

setup-frontend: ## Install frontend dependencies
	cd $(FRONTEND) && npm install

dev: ## Run the backend and frontend dev servers together
	@echo "Backend: http://localhost:8000  Frontend: http://localhost:5173"

dev-backend: ## Run the backend with reload
	cd backend && ./.venv/Scripts/python.exe -m uvicorn backend.app.main:app --reload --port 8000

dev-frontend: ## Run the frontend dev server
	cd $(FRONTEND) && npm run dev

test: test-backend test-frontend ## Run every test suite

test-backend: ## Run the backend test suite
	$(BACKEND_PY) -m pytest backend/tests -q

test-frontend: ## Run the frontend test suite
	cd $(FRONTEND) && npm run test

lint: lint-backend lint-frontend ## Run every linter

lint-backend: ## Lint the backend
	$(BACKEND_PY) -m ruff check backend
	$(BACKEND_PY) -m ruff format --check backend

lint-frontend: ## Type check the frontend
	cd $(FRONTEND) && npx tsc --noEmit

typecheck: typecheck-backend typecheck-frontend ## Run every type checker

typecheck-backend: ## Type check the backend
	$(BACKEND_PY) -m mypy backend/app

typecheck-frontend: ## Type check the frontend
	cd $(FRONTEND) && npx tsc --noEmit

build: build-frontend ## Build production artefacts

build-frontend: ## Build the frontend production bundle
	cd $(FRONTEND) && npm run build

check: lint typecheck test ## Run every check locally

check-backend: lint-backend typecheck-backend test-backend ## Run every backend check

check-frontend: lint-frontend test-frontend build-frontend ## Run every frontend check

clean: ## Remove build artefacts and caches
	rm -rf frontend/dist frontend/node_modules/.vite
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache backend/.mypy_cache backend/.ruff_cache

docker-build: ## Build both container images
	docker build -f backend/Dockerfile -t fx-historical-market-analysis-service-backend:latest .
	docker build -f frontend/Dockerfile -t fx-historical-market-analysis-service-frontend:latest .

docker-up: ## Start the Compose stack
	docker compose up --build -d

docker-down: ## Stop the Compose stack
	docker compose down
