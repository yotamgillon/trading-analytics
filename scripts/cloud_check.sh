#!/usr/bin/env bash
# Build a throwaway venv from requirements.txt ONLY (what Streamlit Community Cloud installs) and
# check that the dashboard runs in it.
set -euo pipefail
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
uv venv --python 3.12 -q "$TMP/venv"
uv pip install -q --python "$TMP/venv/bin/python" -r requirements.txt
cd /
"$TMP/venv/bin/python" "$OLDPWD/scripts/cloud_check.py" 2>&1 | grep -v "missing ScriptRunContext"
