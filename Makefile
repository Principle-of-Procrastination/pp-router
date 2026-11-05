.PHONY: setup init dev test smoke-live eval-live release
setup:
	uv sync --frozen
	uv run python scripts/setup_local.py
	npm ci --prefix frontend
	cd frontend && npx playwright install chromium
init:
	uv run python -m pprouter.cli init --credentials-file .local/credentials.json
dev:
	uv run python scripts/dev.py
test:
	uv run ruff check pprouter tests scripts
	uv run pytest -q
	npm test --prefix frontend
	npm run build --prefix frontend
	npm run test:e2e --prefix frontend
smoke-live:
	uv run python scripts/live.py smoke
eval-live:
	uv run python scripts/live.py evaluate
release:
	uv run python scripts/package_release.py
