"""Regenerate the README screenshots from the DEMO data only.

    uv run --with playwright python scripts/take_screenshots.py

Starts the dashboard against the committed synthetic demo database, drives your installed Google
Chrome (no browser download), and writes docs/img/*.png. Privacy: the private warehouse path is
pointed at a non-existent file and the run aborts unless the page says "Demo data", so a real
warehouse can never end up in a screenshot.
"""

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("docs/img")
PORT = 8765


def free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("localhost", port)) != 0


def main() -> int:
    assert free(PORT), f"port {PORT} is busy"
    env = {
        **os.environ,
        "TRADING_PRIVATE_DB": "/nonexistent/private.duckdb",  # a real warehouse can never load
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    }
    env.pop("TRADING_DEMO_DB", None)  # use the committed prebuilt demo database
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/trading_analytics/dashboard/app.py",
            "--server.headless=true",
            "--client.toolbarMode=viewer",
            f"--server.port={PORT}",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://localhost:{PORT}/_stcore/health", timeout=2)
                break
            except OSError:
                time.sleep(1)
        OUT.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            page = browser.new_page(
                viewport={"width": 1440, "height": 4600}, device_scale_factor=1.5
            )
            page.goto(f"http://localhost:{PORT}")
            page.get_by_text("Where do I make money").first.wait_for(timeout=90_000)
            page.wait_for_selector(".vega-embed", timeout=60_000)
            page.wait_for_function(
                "document.querySelectorAll('.vega-embed').length >= 3", timeout=60_000
            )
            page.wait_for_timeout(2500)  # let the charts and tables finish drawing
            text = page.inner_text("body")
            assert "Demo data" in text and "Private data" not in text, "not the demo: aborting"

            def top(name: str) -> float:
                return page.get_by_role("heading", name=re.compile(name)).first.bounding_box()["y"]

            def shot(file: str, y0: float, y1: float, x0: float = 0, width: float = 1440) -> None:
                page.screenshot(
                    path=str(OUT / file),
                    clip={"x": x0, "y": max(y0 - 12, 0), "width": width, "height": y1 - y0},
                )
                print("wrote", OUT / file)

            heat, ins = top("When do I trade well"), top("^Insights$")
            expander = page.get_by_text("Data quality and caveats").first.bounding_box()
            end = expander["y"] - 8
            shot("dashboard-overview.png", 0, heat)
            shot("dashboard-heatmap-and-conditions.png", heat, ins)
            shot("dashboard-insights.png", ins, end)
            browser.close()
    finally:
        server.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
