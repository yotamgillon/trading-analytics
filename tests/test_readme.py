"""The README is part of the deliverable: its links, diagrams and required sections must not rot."""

import re
from pathlib import Path

README = Path("README.md").read_text()


def test_every_local_link_and_image_exists():
    targets = re.findall(r"\]\(([^)\s]+)\)", README)
    local = [t for t in targets if not t.startswith(("http", "#", "mailto"))]
    assert any(t.endswith(".png") for t in local)
    for target in local:
        assert Path(target.split("#")[0]).exists(), f"README links to missing file: {target}"


def test_screenshots_are_the_demo_ones_and_small_enough():
    for png in Path("docs/img").glob("*.png"):
        assert png.stat().st_size < 1_500_000, png


def test_mermaid_diagrams_are_present_and_balanced():
    blocks = re.findall(r"```mermaid\n(.*?)```", README, re.S)
    assert len(blocks) == 2
    assert blocks[0].lstrip().startswith("flowchart")
    assert blocks[1].lstrip().startswith("erDiagram")
    assert README.count("```") % 2 == 0


def test_required_sections_exist():
    for heading in (
        "## Architecture",
        "## Data model",
        "## How to run",
        "## Key decisions",
        "## Verification",
        "## Limitations and future work",
        "## Deploy the demo on Streamlit Community Cloud",
    ):
        assert heading in README, heading
    for command in ("make setup", "make all", "make dashboard"):
        assert command in README


def test_limitations_cover_the_known_gaps():
    section = README.split("## Limitations and future work")[1].split("\n## ")[0].lower()
    for topic in (
        "1-minute window",
        "make bars",
        "nq bars as a proxy",
        "basis",
        "holiday calendar",
        "yearly",
        "vol_regime",
        "freeze",
        "mid-position",
        "es is not fetched",
        "noise, not skill",
    ):
        assert topic in section, topic


def test_key_decisions_are_all_documented():
    section = README.split("## Key decisions")[1].split("\n## ")[0].lower()
    for topic in (
        "flat-to-flat",
        "gross",
        "utc only",
        "quarantine",
        "one source of truth",
        "no planted edge",
        "permutation",
    ):
        assert topic in section, topic


def test_readme_never_names_private_files_as_committed_or_shows_real_account_strings():
    assert "data/private/" in README  # explains the git-ignored folder
    for fragment in ("11111111", "ACC123"):  # strings from the redacted samples
        assert fragment not in README
