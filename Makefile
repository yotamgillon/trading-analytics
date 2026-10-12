.PHONY: setup test lint guard demo-data demo-db docker-build docker-run docker-smoke cloud-check bars quality quality-demo reconcile ingest transform dashboard all

setup:  ## install deps and enable the git hook that blocks private data
	uv sync --all-extras
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

demo-db:  ## rebuild the committed synthetic demo database data/demo/demo.duckdb
	uv run python scripts/build_demo_db.py

docker-build:  ## build the dashboard image (synthetic demo database baked in)
	docker build -t trading-analytics .

docker-run:  ## serve the dashboard on http://localhost:8501
	docker run --rm -p 8501:8501 trading-analytics

docker-smoke:  ## image checks: contents, health, app renders (needs the image)
	scripts/docker_smoke.sh trading-analytics

cloud-check:  ## run the dashboard in an env with ONLY requirements.txt (like Streamlit Cloud)
	scripts/cloud_check.sh

bars:  ## fetch/accumulate real Yahoo bars into data/warehouse/market.duckdb (gitignored)
	uv run python scripts/daily_bars.py

quality:  ## data quality report: make quality [FILE=path/to/Fills.csv]
	uv run python scripts/quality_report.py $(FILE)

quality-demo:  ## demo data with injected defects -> docs/data_quality_report_demo.md
	uv run python scripts/quality_report.py --inject-defects --write docs/data_quality_report_demo.md

reconcile:  ## compare trades from data/private/Fills.csv with data/private/expected.yaml
	uv run python scripts/reconcile.py

DATASET ?= demo

ingest:  ## clean + pair fills and load the warehouse: make ingest [DATASET=private]
	uv run python scripts/transform.py ingest --dataset $(DATASET)

transform:  ## dbt build (models + tests): make transform [DATASET=private]
	uv run python scripts/transform.py transform --dataset $(DATASET)

dashboard:  ## open the Streamlit dashboard (builds the demo warehouse if missing)
	uv run streamlit run src/trading_analytics/dashboard/app.py

# `make all` = everything end to end. On your own data: make all DATASET=private
# (also compares against data/private/expected.yaml; you run this, it is never read by Claude).
all: lint ingest transform test $(if $(filter private,$(DATASET)),reconcile)
