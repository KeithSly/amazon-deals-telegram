from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .models import Deal, ProductSnapshot, ProductState
from .providers.keepa import KeepaTrackingNotification

DEMO_HOT_ASIN = "B0HOTALRT1"


class DemoProvider:
    def __init__(self, emit_hot_notification: bool = False, hot_only: bool = False):
        self.emit_hot_notification = emit_hot_notification
        self.hot_only = hot_only

    def fetch_deals(self) -> list[Deal]:
        if self.hot_only:
            return []
        now = datetime.now(timezone.utc)
        return [
            Deal("B0DEMO0001", "SSD NVMe 2 TB - oferta de demostracion", 7999, 11999, 33, source_updated_at=now),
            Deal("B0DEMO0002", "Auriculares Bluetooth - oferta de demostracion", 3999, 5999, 33, source_updated_at=now),
        ]

    def discover_new_products(self) -> list[ProductSnapshot]:
        if self.hot_only:
            return []
        now = datetime.now(timezone.utc)
        return [
            ProductSnapshot(
                asin="B0NEWGAME01",
                title="Juego nuevo - edicion especial",
                current_price_cents=6999,
                root_category=599383031,
                tracking_since=now,
                listed_since=now,
                availability_amazon=0,
                is_amazon_offer=True,
            ),
            ProductSnapshot(
                asin="B0PREORD001",
                title="Collector's Edition - reserva",
                current_price_cents=10999,
                root_category=599383031,
                tracking_since=now,
                release_date=now + timedelta(days=60),
                availability_amazon=1,
                is_preorder=True,
                is_amazon_offer=True,
            ),
        ]

    def discover_preorders(self) -> list[ProductSnapshot]:
        if self.hot_only:
            return []
        return [self.discover_new_products()[1]]

    def fetch_restock_deals(self) -> list[Deal]:
        if self.hot_only:
            return []
        now = datetime.now(timezone.utc)
        return [Deal("B0RESTOCK01", "Consola limitada - vuelve el stock", 49999, None, 0, source_updated_at=now)]

    def add_stock_tracking(self, asin: str, metadata: str = "") -> None:
        return None

    def remove_stock_tracking(self, asin: str) -> None:
        return None

    def fetch_tracking_notifications(self, since: int) -> list[KeepaTrackingNotification]:
        if not self.emit_hot_notification:
            return []
        return [
            KeepaTrackingNotification(
                notification_id=f"demo-hot-{int(time.time())}",
                asin=DEMO_HOT_ASIN,
                title="Consola / Collector Edition - alerta HOT de demostracion",
                state=ProductState.BACK_IN_STOCK,
                current_price_cents=49999,
                image_url=None,
                create_date=int(time.time()),
            )
        ]
