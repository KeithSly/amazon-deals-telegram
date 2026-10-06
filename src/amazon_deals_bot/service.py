from __future__ import annotations

import logging
import time
from typing import Protocol

from .config import Config
from .database import DealDatabase
from .models import Deal
from .telegram import TelegramNotifier

LOGGER = logging.getLogger(__name__)


class DealProvider(Protocol):
    def fetch_deals(self) -> list[Deal]: ...


class DealService:
    def __init__(
        self,
        config: Config,
        provider: DealProvider,
        database: DealDatabase,
        notifier: TelegramNotifier | None,
        dry_run: bool,
    ):
        self.config = config
        self.provider = provider
        self.database = database
        self.notifier = notifier
        self.dry_run = dry_run

    def run_once(self) -> dict[str, int]:
        deals = self.provider.fetch_deals()
        deals.sort(key=lambda item: item.discount_percent, reverse=True)
        stats = {"fetched": len(deals), "eligible": 0, "sent": 0, "skipped": 0, "failed": 0}

        for deal in deals:
            if stats["eligible"] >= self.config.max_deals_per_cycle:
                break
            if not self._passes_local_filters(deal):
                stats["skipped"] += 1
                continue
            if not self.database.should_send(
                deal,
                self.config.keepa_price_type,
                self.config.resend_cooldown_hours,
                self.config.resend_min_extra_discount_percent,
            ):
                stats["skipped"] += 1
                continue

            stats["eligible"] += 1
            if self.dry_run:
                LOGGER.info(
                    "DRY RUN | %s | %.2f EUR | -%s%% | https://www.amazon.es/dp/%s",
                    deal.title,
                    deal.current_price_eur,
                    deal.discount_percent,
                    deal.asin,
                )
                continue

            try:
                assert self.notifier is not None
                self.notifier.send(deal)
                self.database.mark_sent(deal, self.config.keepa_price_type)
                stats["sent"] += 1
            except Exception:
                stats["failed"] += 1
                LOGGER.exception("Failed to send deal asin=%s", deal.asin)

        LOGGER.info("Cycle finished: %s", stats)
        return stats

    def run_forever(self) -> None:
        while True:
            started = time.monotonic()
            try:
                self.run_once()
            except Exception:
                LOGGER.exception("Deal cycle failed")
            elapsed = time.monotonic() - started
            wait_seconds = max(1.0, self.config.poll_seconds - elapsed)
            LOGGER.info("Next check in %.0f seconds", wait_seconds)
            time.sleep(wait_seconds)

    def _passes_local_filters(self, deal: Deal) -> bool:
        if deal.discount_percent < self.config.min_discount_percent:
            return False
        if deal.current_price_eur < self.config.min_price_eur:
            return False
        if deal.current_price_eur > self.config.max_price_eur:
            return False
        title_lower = deal.title.lower()
        return not any(word in title_lower for word in self.config.title_exclude_words)
