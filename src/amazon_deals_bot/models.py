from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Deal:
    asin: str
    title: str
    current_price_cents: int
    reference_price_cents: int | None
    discount_percent: int
    image_url: str | None = None
    root_category: int | None = None
    source_updated_at: datetime | None = None
    lightning_end: datetime | None = None

    @property
    def current_price_eur(self) -> float:
        return self.current_price_cents / 100.0

    @property
    def reference_price_eur(self) -> float | None:
        if self.reference_price_cents is None:
            return None
        return self.reference_price_cents / 100.0
