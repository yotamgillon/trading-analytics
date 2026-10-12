# Dashboard image: the lean runtime only (no dbt, no Yahoo client). It serves the committed,
# synthetic demo database. Nothing from data/private/ or data/warehouse/ can enter the image:
# .dockerignore is an allow-list (see it), and CI checks the built image's file list.
FROM python:3.12-slim

# uv resolves exactly what uv.lock pins, so the image matches the tested environment.
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# 1) dependencies first (cached until pyproject.toml / uv.lock change); --no-dev and no extras
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) the application: package, the mart SQL the dashboard renders, the synthetic demo database
COPY src ./src
COPY dbt_project/macros ./dbt_project/macros
COPY dbt_project/models/marts ./dbt_project/models/marts
COPY data/demo/demo.duckdb ./data/demo/demo.duckdb
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8501/_stcore/health', timeout=4)"

CMD ["streamlit", "run", "src/trading_analytics/dashboard/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
