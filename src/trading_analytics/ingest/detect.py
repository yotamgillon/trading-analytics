"""Format auto-detection from CSV headers (the file's contents are never needed)."""

from collections.abc import Iterable

from trading_analytics.ingest.adapters import ADAPTERS, Adapter


class UnknownFormatError(ValueError):
    pass


class AmbiguousFormatError(ValueError):
    pass


def detect_adapter(headers: Iterable[str]) -> type[Adapter]:
    cols = {h.strip() for h in headers}
    matches = [a for a in ADAPTERS if a.signature <= cols]
    if not matches:
        supported = {a.name: sorted(a.signature) for a in ADAPTERS}
        raise UnknownFormatError(f"No adapter matches headers. Supported signatures: {supported}")
    if len(matches) > 1:
        raise AmbiguousFormatError(f"Multiple adapters match: {[a.name for a in matches]}")
    return matches[0]
