"""Findings and the data quality report: a record of everything the pipeline changed or doubts."""

from dataclasses import dataclass, field

import pandas as pd

SEVERITIES = ("fixed", "warning", "info")
ICON = {"fixed": "FIXED", "warning": "WARN ", "info": "INFO "}


class QualityError(ValueError):
    """Data problem that cannot be fixed automatically (e.g. conflicting duplicates)."""


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str  # fixed = changed/excluded automatically | warning = kept, needs a look | info
    count: int
    message: str
    examples: tuple[str, ...] = ()  # fill ids only; never account identifiers

    def __post_init__(self):
        assert self.severity in SEVERITIES, self.severity


def examples_of(values, limit: int = 5) -> tuple[str, ...]:
    return tuple(str(v) for v in list(pd.Series(values).head(limit)))


@dataclass
class QualityReport:
    rows_raw: int = 0
    rows_clean: int = 0
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding | None) -> None:
        if finding is not None and finding.count > 0:
            self.findings.append(finding)

    def of(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def clean(self) -> bool:
        return not self.of("fixed") and not self.of("warning")

    def render(self, markdown: bool = False) -> str:
        head = f"{self.rows_raw} raw rows -> {self.rows_clean} clean fills"
        if not self.findings:
            body = "No issues found."
            return (
                f"## Data quality report\n\n{head}\n\n{body}\n" if markdown else f"{head}\n{body}"
            )
        lines = []
        for sev in SEVERITIES:
            for f in self.of(sev):
                ex = f" (fill ids {', '.join(f.examples)})" if f.examples else ""
                if markdown:
                    lines.append(
                        f"- **{ICON[sev].strip()}** `{f.check}` x{f.count}: {f.message}{ex}"
                    )
                else:
                    lines.append(f"  [{ICON[sev]}] {f.check} x{f.count}: {f.message}{ex}")
        if markdown:
            return f"## Data quality report\n\n{head}\n\n" + "\n".join(lines) + "\n"
        return head + "\n" + "\n".join(lines)
