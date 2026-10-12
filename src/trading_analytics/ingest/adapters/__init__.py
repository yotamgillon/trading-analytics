from trading_analytics.ingest.adapters.base import Adapter
from trading_analytics.ingest.adapters.tradovate_fills import TradovateFillsAdapter

# Register new platforms here: one adapter module + one fixture + one test.
ADAPTERS: list[type[Adapter]] = [TradovateFillsAdapter]

__all__ = ["ADAPTERS", "Adapter", "TradovateFillsAdapter"]
