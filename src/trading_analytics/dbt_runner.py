"""Run `dbt build` (models + tests) against one DuckDB file. Run from the repo root."""

import os
import subprocess
import sys
from pathlib import Path


def run_dbt(db: Path, quiet: bool = False, dbt_vars: str | None = None) -> int:
    dbt = Path(sys.executable).parent / "dbt"
    cmd = [str(dbt) if dbt.exists() else "dbt", "build", "--project-dir", "dbt_project"]
    cmd += ["--profiles-dir", "dbt_project"]
    if dbt_vars:
        cmd += ["--vars", dbt_vars]
    out = subprocess.DEVNULL if quiet else None
    return subprocess.run(
        cmd, env={**os.environ, "DBT_DUCKDB_PATH": str(db)}, stdout=out
    ).returncode
