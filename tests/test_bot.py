from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from amazon_deals_bot.config import Config
from amazon_deals_bot.database import DealDatabase
from amazon_deals_bot.demo import DemoProvider
from amazon_deals_bot.engines.discovery import DiscoveryEngine
from amazon_deals_bot.models import Alert, AlertKind, Deal, Priority, ProductSnapshot, ProductState
from amazon_deals_bot.providers.keepa import KeepaProvider, keepa_time_to_datetime
from amazon_deals_bot.service import MonitoringService
from amazon_deals_bot.telegram import TelegramNotifier


def make_config(**overrides) -> Config:
    base = Config(
        source="demo",
        keepa_api_key="test-key",
        keepa_domain_id=9,
        keepa_price_type=0,
        keepa_date_range=3,
        keepa_max_pages=1,
        keepa_product_update_hours=1,
        keepa_tracking_update_hours=1,
        min_discount_percent=25,
        min_price_eur=5.0,
        max_price_eur=1500.0,
        min_rating=4.0,
        only_lowest_90=False,
        must_have_amazon_offer=True,
        include_categories=(),
        exclude_categories=(),
        title_exclude_words=("renewed",),
        max_deals_per_cycle=20,
        discovery_enabled=True,
        discovery_root_categories=(599383031,),
        discovery_lookback_minutes=30,
        discovery_per_page=50,
        discovery_max_pages=1,
        preorder_enabled=True,
        preorder_lookback_minutes=60,
        restock_enabled=True,
        keepa_tracking_enabled=True,
        telegram_bot_token="bot-token",
        telegram_public_chat_id="public",
        telegram_personal_chat_id="personal",
        telegram_send_image=False,
        telegram_disable_notification=False,
        amazon_associate_tag="",
        affiliate_disclosure="Enlace de afiliado",
        poll_seconds=600,
        resend_cooldown_hours=24.0,
        resend_min_extra_discount_percent=5.0,
        product_expire_hours=720,
        db_path=":memory:",
        http_timeout_seconds=20,
        log_level="INFO",
        dry_run=True,
    )
    return replace(base, **overrides)


class KeepaTests(unittest.TestCase):
    def test_parse_deal(self) -> None:
        config = make_config(source="keepa")
        provider = KeepaProvider(config)
        raw = {
            "asin": "B00TEST123",
            "title": "<b>Test</b> Product",
            "rootCat": 599383031,
            "image": [54, 49, 107, 51, 76, 97, 121, 55, 74, 85, 76, 46, 106, 112, 103],
            "current": [7999],
            "avg": [[10000], [11000], [11500], [11999]],
            "deltaPercent": [[20], [27], [30], [33]],
            "lastUpdate": 7661998,
            "lightningEnd": 0,
        }
        deal = provider._parse_deal(raw)
        assert deal is not None
        self.assertEqual(deal.title, "Test Product")
        self.assertEqual(deal.current_price_cents, 7999)
        self.assertEqual(deal.reference_price_cents, 11999)
        self.assertEqual(deal.discount_percent, 33)
        self.assertTrue(deal.image_url.endswith("61k3Lay7JUL.jpg"))

    def test_deal_query_restock_switch(self) -> None:
        provider = KeepaProvider(make_config(source="keepa"))
        normal = provider._build_deal_query(0, False)
        restock = provider._build_deal_query(0, True)
        self.assertEqual(normal["domainId"], 9)
        self.assertEqual(normal["deltaPercentRange"], [25, 100])
        self.assertFalse(normal["isBackInStock"])
        self.assertTrue(restock["isBackInStock"])
        self.assertEqual(restock["deltaPercentRange"], [0, 100])

    def test_parse_product_preorder(self) -> None:
        provider = KeepaProvider(make_config(source="keepa"))
        raw = {
            "asin": "B0PREORD01",
            "title": "Collector Edition",
            "rootCategory": 599383031,
            "availabilityAmazon": 1,
            "trackingSince": 7661998,
            "releaseDate": 7669998,
            "imagesCSV": "image.jpg,other.jpg",
            "stats": {"current": [10999]},
        }
        product = provider._parse_product(raw)
        assert product is not None
        self.assertTrue(product.is_preorder)
        self.assertEqual(product.natural_state, ProductState.PREORDER)
        self.assertEqual(product.current_price_cents, 10999)

    def test_keepa_time_conversion(self) -> None:
        dt = keepa_time_to_datetime(1)
        assert dt is not None
        self.assertEqual(dt.tzinfo, timezone.utc)


class DatabaseTests(unittest.TestCase):
    def test_deal_dedup_and_lower_price_resend(self) -> None:
        db = DealDatabase(":memory:")
        first = Deal("A", "Product", 10000, 14000, 29)
        self.assertTrue(db.should_send_deal(first, 0, 24, 5))
        db.mark_deal_sent(first, 0)
        self.assertFalse(db.should_send_deal(first, 0, 24, 5))
        self.assertFalse(db.should_send_deal(Deal("A", "Product", 9700, 14000, 31), 0, 24, 5))
        self.assertTrue(db.should_send_deal(Deal("A", "Product", 9000, 14000, 36), 0, 24, 5))
        db.close()

    def test_watchlist(self) -> None:
        db = DealDatabase(":memory:")
        db.add_watch("B0TEST0001", Priority.HOT, True)
        item = db.list_watchlist()[0]
        self.assertEqual(item.priority, Priority.HOT)
        self.assertTrue(item.personal)
        self.assertFalse(item.tracking_synced)
        db.mark_tracking_synced(item.asin)
        self.assertTrue(db.list_watchlist()[0].tracking_synced)
        db.close()

    def test_product_state_history(self) -> None:
        db = DealDatabase(":memory:")
        product = ProductSnapshot("B0TEST0002", "Game", 6999, availability_amazon=1, is_preorder=True)
        db.upsert_product(product, ProductState.PREORDER)
        self.assertEqual(db.get_product_state(product.asin), ProductState.PREORDER)
        count = db.connection.execute("SELECT COUNT(*) AS n FROM state_history WHERE asin = ?", (product.asin,)).fetchone()["n"]
        self.assertGreaterEqual(count, 1)
        db.close()


class TelegramTests(unittest.TestCase):
    def test_public_affiliate_and_personal_clean_url(self) -> None:
        notifier = TelegramNotifier(make_config(amazon_associate_tag="example-21", dry_run=False))
        self.assertEqual(notifier.amazon_url("B00ABC1234"), "https://www.amazon.es/dp/B00ABC1234?tag=example-21")
        self.assertEqual(notifier.amazon_url("B00ABC1234", personal=True), "https://www.amazon.es/dp/B00ABC1234")

    def test_preorder_message(self) -> None:
        notifier = TelegramNotifier(make_config())
        product = ProductSnapshot("B0PREORD01", "Game & Collector", 10999, is_preorder=True, availability_amazon=1)
        alert = Alert(AlertKind.PREORDER, ProductState.PREORDER, product, Priority.NEW_RELEASE)
        message = notifier.render_message(alert)
        self.assertIn("NUEVA RESERVA", message)
        self.assertIn("Game &amp; Collector", message)
        self.assertIn("109,99 EUR", message)


class EngineTests(unittest.TestCase):
    def test_discovery_emits_new_and_preorder(self) -> None:
        config = make_config()
        db = DealDatabase(":memory:")
        alerts = DiscoveryEngine(config, DemoProvider(), db).collect()
        self.assertEqual({a.kind for a in alerts}, {AlertKind.NEW_PRODUCT, AlertKind.PREORDER})
        db.close()

    def test_full_demo_cycle_dry_run(self) -> None:
        config = make_config()
        db = DealDatabase(":memory:")
        service = MonitoringService(config, DemoProvider(), db, None, dry_run=True)
        stats = service.run_once("all")
        self.assertGreaterEqual(stats["collected"], 5)
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(stats["failed"], 0)
        db.close()


class ConfigTests(unittest.TestCase):
    def test_reject_non_spanish_domain(self) -> None:
        with self.assertRaises(ValueError):
            make_config(keepa_domain_id=3).validate(source_override="demo", dry_run_override=True)

    def test_default_gaming_category_is_present(self) -> None:
        self.assertEqual(make_config().discovery_root_categories, (599383031,))


if __name__ == "__main__":
    unittest.main()
