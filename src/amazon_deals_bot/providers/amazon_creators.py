from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AmazonCreatorsProvider:
    """Placeholder boundary for Amazon Creators API.

    The monitor currently uses Keepa for discovery, prices and stock.  This
    adapter exists so catalog enrichment can be switched to Amazon's official
    Creators API later without coupling the engines to Keepa response shapes.
    """

    marketplace: str = "www.amazon.es"

    def is_configured(self) -> bool:
        return False
