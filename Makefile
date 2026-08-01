.PHONY: dev demo test lint up down logs probe backup

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

demo:
	DEMO_MODE=true DATABASE_URL=sqlite:///./data/gate_bots.db uvicorn app.main:app --reload --port 8080

test:
	python -m pytest -q

lint:
	ruff check app scripts tests

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

probe:
	python scripts/probe_gate.py

backup:
	python scripts/backup_db.py --source data/gate_bots.db --directory backups
