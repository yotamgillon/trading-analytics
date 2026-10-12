.PHONY: setup test lint guard ingest transform dashboard all

setup:  ## install deps and enable the git hook that blocks private data
	uv sync
	git config core.hooksPath .githooks

test: guard
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

guard:  ## fail if private/real data is tracked or staged
	python3 scripts/check_no_private.py

# Filled in by later phases
ingest transform dashboard:
	@echo "'$@' is not implemented yet (see phased plan)"; exit 1

all: ingest transform test
