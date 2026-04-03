test:
	uv run pytest

integration-test:
	docker exec sage-mcp bash -lc "cd /workspace && sage -python -m pytest" | tee integration.log
	tar -czf integration-artifacts.tar.gz integration.log || true

lint:
	uv run ruff check

build:
	uv run python scripts/build_release.py

sage-container:
	./scripts/setup_sage_container.sh

cli-integration:
	docker compose up -d
	uv run python -m tests.cli_integration.run_cli_tests --cli both

all: test integration-test
