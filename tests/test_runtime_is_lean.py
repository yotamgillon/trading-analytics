"""The deployed dashboard must run without dbt or the Yahoo client, from the committed demo DB."""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

HEAVY = ("dbt", "yfinance")


def names(requirements):
    return {re.split(r"[<>=!~\[ ]", r.strip())[0].lower() for r in requirements}


def test_core_dependencies_exclude_dbt_and_yahoo_and_requirements_txt_mirrors_them():
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    core = project["dependencies"]
    assert not any(n.startswith(HEAVY) for n in names(core)), "dbt/yfinance belong in [pipeline]"
    extra = names(project["optional-dependencies"]["pipeline"])
    assert {"dbt-duckdb", "yfinance"} <= extra
    lines = [
        line.strip()
        for line in Path("requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert sorted(lines) == sorted(core), "requirements.txt must mirror [project].dependencies"


def test_app_runs_on_the_committed_demo_db_with_dbt_and_yfinance_unimportable():
    code = """
import sys
sys.modules['dbt'] = None          # any 'import dbt...' now raises ImportError
sys.modules['yfinance'] = None
from streamlit.testing.v1 import AppTest
from trading_analytics.dashboard import data
assert data.ensure_demo_warehouse() == data.PREBUILT_DEMO_DB, 'should use the prebuilt DB'
at = AppTest.from_file('src/trading_analytics/dashboard/app.py', default_timeout=180).run()
assert not at.exception, [e.value for e in at.exception]
trades = next(m.value for m in at.metric if m.label == 'Trades')
assert trades == '500', trades
assert not any(m.startswith(('dbt', 'yfinance')) for m in sys.modules if sys.modules[m]), 'loaded'
print('ok')
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().endswith("ok")


def test_nothing_in_the_dashboard_package_imports_dbt_or_yahoo_at_module_level():
    for path in Path("src/trading_analytics/dashboard").glob("*.py"):
        top_level = [
            line
            for line in path.read_text().splitlines()
            if re.match(r"^(import|from) (dbt|yfinance)\b", line)
        ]
        assert not top_level, (path, top_level)
