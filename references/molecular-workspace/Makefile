.PHONY: setup test dev-api dev-web tokens check

setup:            ## install backend (editable) + frontend deps
	cd backend && pip install -e ".[dev]"
	cd frontend && npm install

test:             ## backend tests
	cd backend && python -m pytest -q

tokens:           ## design/tokens.json -> frontend/src/design/tokens.css (+ components.css copy)
	python3 design/build_tokens.py

dev-api:          ## FastAPI on :8000
	cd backend && uvicorn mw.api.app:app --reload --port 8000

dev-web:          ## Next.js on :3000 (proxies /api -> :8000)
	cd frontend && npm run dev

check: test       ## everything an agent must run before saying "done"
	cd frontend && npm run typecheck && npm run build
