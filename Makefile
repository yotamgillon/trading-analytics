.PHONY: setup test lint guard demo-data bars quality quality-demo reconcile ingest transform dashboard all

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

demo-data:  ## regenerate the synthetic demo export + bars (data/demo/)
	uv run python -m trading_analytics.demo

bars:  ## fetch/accumulate real Yahoo bars into data/warehouse/market.duckdb (gitignored)
	uv run python scripts/daily_bars.py

quality:  ## data quality report: make quality [FILE=path/to/Fills.csv]
	uv run python scripts/quality_report.py $(FILE)

quality-demo:  ## demo data with injected defects -> docs/data_quality_report_demo.md
	uv run python scripts/quality_report.py --inject-defects --write docs/data_quality_report_demo.md

reconcile:  ## compare trades from data/private/Fills.csv with data/private/expected.yaml
	uv run python scripts/reconcile.py

# Filled in by later phases
ingest transform dashboard:
	@echo "'$@' is not implemented yet (see phased plan)"; exit 1

all: ingest transform test
