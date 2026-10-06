from __future__ import annotations

from datetime import datetime, timezone

from .models import Deal


class DemoProvider:
    def fetch_deals(self) -> list[Deal]:
        now = datetime.now(timezone.utc)
        return [
            Deal(
                asin="B0DEMO0001",
                title="SSD NVMe 2 TB - oferta de demostracion",
                current_price_cents=7999,
                reference_price_cents=11999,
                discount_percent=33,
                source_updated_at=now,
            ),
            Deal(
                asin="B0DEMO0002",
                title="Auriculares Bluetooth - oferta de demostracion",
                current_price_cents=3999,
                reference_price_cents=5999,
                discount_percent=33,
                source_updated_at=now,
            ),
        ]
