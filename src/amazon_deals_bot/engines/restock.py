from __future__ import annotations

import logging

from ..config import Config
from ..database import DealDatabase
from ..models import Alert, AlertKind, Priority, ProductSnapshot, ProductState

LOGGER = logging.getLogger(__name__)


class RestockEngine:
    def __init__(self, config: Config, provider, database: DealDatabase):
        self.config = config
        self.provider = provider
        self.database = database
        self.latest_notification_time = 0

    def collect(self) -> list[Alert]:
        if not self.config.restock_enabled:
            return []
        alerts: list[Alert] = []

        # Broad recent restocks in the configured discovery categories.
        for deal in self.provider.fetch_restock_deals():
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
            self.database.record_state(product.asin, ProductState.BACK_IN_STOCK, product.current_price_cents, {"source": "deal-restock"})
            occurrence = deal.source_updated_at.isoformat() if deal.source_updated_at else "recent"
            alerts.append(Alert(AlertKind.RESTOCK, ProductState.BACK_IN_STOCK, product, Priority.RESTOCK, notification_id=f"deal:{occurrence}"))

        if not self.config.keepa_tracking_enabled:
            return alerts

        # Ensure manually watched/HOT ASINs are registered in Keepa Tracking.
        for watch in self.database.list_watchlist(only_unsynced=True):
            try:
                self.provider.add_stock_tracking(watch.asin, metadata=f"amazon-deals-telegram|{watch.priority.value}|personal={int(watch.personal)}")
                self.database.mark_tracking_synced(watch.asin)
            except Exception:
                LOGGER.exception("Could not sync Keepa tracking for asin=%s", watch.asin)

        since = self.database.get_int_setting("keepa_notifications_since", 0)
        notifications = self.provider.fetch_tracking_notifications(since)
        max_create_date = since
        watches = {item.asin: item for item in self.database.list_watchlist()}
        for notification in notifications:
            max_create_date = max(max_create_date, notification.create_date)
            if not notification.asin or self.database.notification_processed(notification.notification_id):
                continue
            watch = watches.get(notification.asin.upper())
            personal = bool(watch.personal) if watch else False
            priority = watch.priority if watch else Priority.RESTOCK
            product = ProductSnapshot(
                asin=notification.asin,
                title=notification.title,
                current_price_cents=notification.current_price_cents,
                image_url=notification.image_url,
                availability_amazon=0 if notification.state == ProductState.BACK_IN_STOCK else -1,
                is_amazon_offer=True,
            )
            stable_state = ProductState.AVAILABLE if notification.state == ProductState.BACK_IN_STOCK else ProductState.OUT_OF_STOCK
            self.database.upsert_product(product, stable_state)
            self.database.record_state(product.asin, notification.state, product.current_price_cents, {"source": "keepa-tracking", "notification_id": notification.notification_id})
            kind = AlertKind.RESTOCK if notification.state == ProductState.BACK_IN_STOCK else AlertKind.OUT_OF_STOCK
            alerts.append(
                Alert(
                    kind,
                    notification.state,
                    product,
                    Priority.HOT if priority == Priority.HOT else priority,
                    personal=personal,
                    notification_id=notification.notification_id,
                )
            )

        self.latest_notification_time = max_create_date
        return alerts
