from __future__ import annotations

from ..config import Config
from ..database import DealDatabase
from ..models import Alert, AlertKind, Priority, ProductState


class PreorderEngine:
    def __init__(self, config: Config, provider, database: DealDatabase):
        self.config = config
        self.provider = provider
        self.database = database

    def collect(self) -> list[Alert]:
        if not self.config.preorder_enabled:
            return []
        alerts: list[Alert] = []
        for product in self.provider.discover_preorders():
            if any(word in product.title.lower() for word in self.config.title_exclude_words):
                continue
            self.database.upsert_product(product, ProductState.PREORDER)
            self.database.record_state(product.asin, ProductState.PREORDER, product.current_price_cents, {"source": "preorder"})
            alerts.append(Alert(AlertKind.PREORDER, ProductState.PREORDER, product, Priority.NEW_RELEASE))
        return alerts
