from __future__ import annotations

from ..config import Config
from ..database import DealDatabase
from ..models import Alert, AlertKind, Priority, ProductState


class DiscoveryEngine:
    def __init__(self, config: Config, provider, database: DealDatabase):
        self.config = config
        self.provider = provider
        self.database = database

    def collect(self) -> list[Alert]:
        if not self.config.discovery_enabled:
            return []
        alerts: list[Alert] = []
        for product in self.provider.discover_new_products():
            if any(word in product.title.lower() for word in self.config.title_exclude_words):
                continue
            natural = product.natural_state
            self.database.upsert_product(product, natural)
            if product.is_preorder:
                state = ProductState.PREORDER
                kind = AlertKind.PREORDER
                priority = Priority.NEW_RELEASE
            else:
                state = ProductState.NEW
                kind = AlertKind.NEW_PRODUCT
                priority = Priority.NEW_RELEASE
            self.database.record_state(product.asin, state, product.current_price_cents, {"source": "discovery"})
            alerts.append(Alert(kind, state, product, priority))
        return alerts
