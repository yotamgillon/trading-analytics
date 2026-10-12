"""The Docker build context is an allow-list; keep private data out of the image by construction."""

from pathlib import Path

FORBIDDEN = ("data/private", "data/warehouse", ".git", ".env", "private", "market.duckdb")


def rules():
    return [
        line.strip()
        for line in Path(".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def test_dockerignore_excludes_everything_by_default():
    assert rules()[0] == "*"


def test_dockerignore_never_re_includes_private_or_warehouse_paths():
    for rule in rules():
        if rule.startswith("!"):
            assert not any(bad in rule.lower() for bad in FORBIDDEN), rule


def test_the_only_database_that_can_enter_the_image_is_the_synthetic_demo():
    includes = [r for r in rules() if r.startswith("!")]
    dbs = [r for r in includes if "duckdb" in r]
    assert dbs == ["!data/demo/demo.duckdb"]


def test_dockerfile_copies_only_allowed_paths_and_runs_non_root_without_dev_or_extras():
    text = Path("Dockerfile").read_text()
    copies = [
        line.split()[1]
        for line in text.splitlines()
        if line.startswith("COPY ") and "--from" not in line
    ]
    assert set(copies) == {
        "pyproject.toml",
        "src",
        "dbt_project/macros",
        "dbt_project/models/marts",
        "data/demo/demo.duckdb",
    }
    assert "--no-dev" in text and "--all-extras" not in text and "--extra" not in text
    assert "USER app" in text and "HEALTHCHECK" in text
