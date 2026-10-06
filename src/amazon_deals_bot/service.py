from __future__ import annotations

import logging
import time

from .config import Config
from .database import DealDatabase
from .engines import DealEngine, DiscoveryEngine, PreorderEngine, RestockEngine
from .models import Alert
from .telegram import TelegramNotifier

LOGGER = logging.getLogger(__name__)


class MonitoringService:
    def __init__(self, config: Config, provider, database: DealDatabase, notifier: TelegramNotifier | None, dry_run: bool):
        self.config = config
        self.provider = provider
        self.database = database
        self.notifier = notifier
        self.dry_run = dry_run
        self.deals = DealEngine(config, provider, database)
        self.discovery = DiscoveryEngine(config, provider, database)
        self.preorders = PreorderEngine(config, provider, database)
        self.restock = RestockEngine(config, provider, database)

    def run_once(self, mode: str = "all") -> dict[str, int]:
        stats = {"collected": 0, "sent": 0, "skipped": 0, "failed": 0, "expired": 0}
        alerts: list[Alert] = []

        if mode in {"all", "deals"}:
            alerts.extend(self.deals.collect())
        if mode in {"all", "discovery"}:
            alerts.extend(self.discovery.collect())
        if mode in {"all", "preorders"}:
            alerts.extend(self.preorders.collect())
        if mode in {"all", "restock"}:
            alerts.extend(self.restock.collect())

        stats["collected"] = len(alerts)
        unique: dict[str, Alert] = {}
        for alert in alerts:
            unique.setdefault(alert.event_key, alert)

        tracking_failed = False
        for alert in unique.values():
            if self.database.event_was_sent(alert.event_key):
                stats["skipped"] += 1
                continue
            if self.dry_run:
                LOGGER.info(
                    "DRY RUN | kind=%s priority=%s personal=%s asin=%s title=%s price=%s url=%s",
                    alert.kind.value,
                    alert.priority.value,
                    alert.personal,
                    alert.product.asin,
                    alert.product.title,
                    alert.product.current_price_cents,
                    self._dry_run_url(alert),
                )
                continue
            try:
                assert self.notifier is not None
                self.notifier.send(alert)
                self.database.mark_event_sent(
                    alert.event_key,
                    alert.product.asin,
                    alert.state,
                    {"kind": alert.kind.value, "priority": alert.priority.value, "personal": alert.personal},
                )
                if alert.deal is not None:
                    self.database.mark_deal_sent(alert.deal, self.config.keepa_price_type)
                if alert.notification_id and not alert.notification_id.startswith("deal:"):
                    self.database.mark_notification_processed(alert.notification_id)
                stats["sent"] += 1
            except Exception:
                stats["failed"] += 1
                if alert.notification_id and not alert.notification_id.startswith("deal:"):
                    tracking_failed = True
                LOGGER.exception("Failed to send alert kind=%s asin=%s", alert.kind.value, alert.product.asin)

        if (
            mode in {"all", "restock"}
            and not self.dry_run
            and not tracking_failed
            and self.restock.latest_notification_time > self.database.get_int_setting("keepa_notifications_since", 0)
        ):
            self.database.set_setting("keepa_notifications_since", self.restock.latest_notification_time)

        stats["expired"] = self.database.expire_stale_products(self.config.product_expire_hours)
        LOGGER.info("Cycle finished mode=%s stats=%s", mode, stats)
        return stats

    def run_forever(self, mode: str = "all") -> None:
        while True:
            started = time.monotonic()
            try:
                self.run_once(mode)
            except Exception:
                LOGGER.exception("Monitoring cycle failed")
            elapsed = time.monotonic() - started
            wait_seconds = max(1.0, self.config.poll_seconds - elapsed)
            LOGGER.info("Next check in %.0f seconds", wait_seconds)
            time.sleep(wait_seconds)

    def _dry_run_url(self, alert: Alert) -> str:
        base = f"https://www.amazon.es/dp/{alert.product.asin}"
        if alert.personal or not self.config.amazon_associate_tag:
            return base
        return f"{base}?tag={self.config.amazon_associate_tag}"


# Backwards-compatible name from v0.1.
DealService = MonitoringService
