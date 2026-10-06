from __future__ import annotations

from ..config import Config
from ..database import DealDatabase
from ..models import Alert, AlertKind, Priority, ProductSnapshot, ProductState


class DealEngine:
    def __init__(self, config: Config, provider, database: DealDatabase):
        self.config = config
        self.provider = provider
        self.database = database

    def collect(self) -> list[Alert]:
        deals = sorted(self.provider.fetch_deals(), key=lambda x: x.discount_percent, reverse=True)
        alerts: list[Alert] = []
        for deal in deals:
            if len(alerts) >= self.config.max_deals_per_cycle:
                break
            if deal.discount_percent < self.config.min_discount_percent:
                continue
            if not (self.config.min_price_eur <= deal.current_price_eur <= self.config.max_price_eur):
                continue
            if any(word in deal.title.lower() for word in self.config.title_exclude_words):
                continue
            if not self.database.should_send_deal(
                deal,
                self.config.keepa_price_type,
                self.config.resend_cooldown_hours,
                self.config.resend_min_extra_discount_percent,
            ):
                continue
            product = ProductSnapshot(
                asin=deal.asin,
                title=deal.title,
                current_price_cents=deal.current_price_cents,
                image_url=deal.image_url,
                root_category=deal.root_category,
                source_updated_at=deal.source_updated_at,
                availability_amazon=0,
                is_amazon_offer=True,
            )
            self.database.upsert_product(product, ProductState.AVAILABLE)
            self.database.record_state(product.asin, ProductState.DEAL, product.current_price_cents, {"discount_percent": deal.discount_percent})
            alerts.append(Alert(AlertKind.DEAL, ProductState.DEAL, product, Priority.NORMAL, deal=deal))
        return alerts
