#!/usr/bin/env bash
# Smoke test for the dashboard image: it must (1) contain exactly one database, the synthetic demo,
# and nothing from data/private or data/warehouse, (2) start, report healthy and serve the app,
# (3) run as a non-root user. Usage: scripts/docker_smoke.sh [image]   (default: trading-analytics)
set -euo pipefail
IMAGE="${1:-trading-analytics}"
NAME="ta-smoke-$$"
PORT="${SMOKE_PORT:-8599}"
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

echo "== image contents"
dbs=$(docker run --rm --entrypoint sh "$IMAGE" -c "find /app -name '*.duckdb' -o -name '*.wal'")
[ "$dbs" = "/app/data/demo/demo.duckdb" ] || { echo "unexpected database files:"; echo "$dbs"; exit 1; }
docker run --rm --entrypoint sh "$IMAGE" -c "test ! -e /app/data/private && test ! -e /app/data/warehouse" \
  || { echo "private/warehouse folders exist in the image"; exit 1; }
[ "$(docker run --rm --entrypoint id "$IMAGE" -u)" != "0" ] || { echo "image runs as root"; exit 1; }
echo "ok: only /app/data/demo/demo.duckdb, no private/warehouse dirs, non-root"

echo "== serving"
docker run -d --name "$NAME" -p "$PORT:8501" "$IMAGE" >/dev/null
for i in $(seq 1 60); do
  if curl -fsS "http://localhost:$PORT/_stcore/health" >/dev/null 2>&1; then break; fi
  sleep 2
  [ "$i" -lt 60 ] || { echo "app never became healthy"; docker logs "$NAME" | tail -30; exit 1; }
done
code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/")
[ "$code" = "200" ] || { echo "GET / returned $code"; exit 1; }
echo "ok: healthy, GET / -> 200"

echo "== the app itself runs (headless script run inside the container)"
docker exec -i "$NAME" python - <<'PY'
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("src/trading_analytics/dashboard/app.py", default_timeout=180).run()
assert not at.exception, [e.value for e in at.exception]
trades = next(m.value for m in at.metric if m.label == "Trades")
assert trades == "500", trades
print("ok: app rendered, 500 trades")
PY
