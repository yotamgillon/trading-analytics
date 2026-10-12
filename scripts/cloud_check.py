"""Run from a Streamlit-Cloud-like environment: only requirements.txt installed (no project
install, no dbt, no yfinance). Fails unless the app renders the committed demo (500 trades).
`make cloud-check` builds such an environment in a temp folder and runs this inside it."""

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for heavy in ("dbt", "yfinance", "trading_analytics"):
    assert importlib.util.find_spec(heavy) is None, f"{heavy} must NOT be installed here"

os.chdir(ROOT)
from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file("src/trading_analytics/dashboard/app.py", default_timeout=180).run()
assert not at.exception, [e.value for e in at.exception]
trades = next(m.value for m in at.metric if m.label == "Trades")
assert trades == "500", trades
print("cloud-like environment OK: app rendered 500 demo trades")
sys.exit(0)
