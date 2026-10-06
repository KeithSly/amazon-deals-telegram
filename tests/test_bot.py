from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from amazon_deals_bot.config import Config
from amazon_deals_bot.database import DealDatabase
from amazon_deals_bot.keepa import KeepaProvider
from amazon_deals_bot.models import Deal
from amazon_deals_bot.telegram import TelegramNotifier


def make_config(**overrides) -> Config:
    base = Config(
        source="demo",
        keepa_api_key="test-key",
        keepa_domain_id=9,
        keepa_price_type=0,
        keepa_date_range=0,
        keepa_max_pages=1,
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
        telegram_bot_token="bot-token",
        telegram_chat_id="12345",
        telegram_send_image=False,
        telegram_disable_notification=False,
        amazon_associate_tag="",
        affiliate_disclosure="Enlace de afiliado",
        poll_seconds=600,
        resend_cooldown_hours=24.0,
        resend_min_extra_discount_percent=5.0,
        db_path=":memory:",
        http_timeout_seconds=20,
        log_level="INFO",
        dry_run=True,
    )
    return replace(base, **overrides)


class KeepaTests(unittest.TestCase):
    def test_parse_deal(self) -> None:
        config = make_config(source="keepa", keepa_date_range=3)
        provider = KeepaProvider(config)
        raw = {
            "asin": "B00TEST123",
            "title": "<b>Test</b> Product",
            "rootCat": 123,
            "image": [54, 49, 107, 51, 76, 97, 121, 55, 74, 85, 76, 46, 106, 112, 103],
            "current": [7999],
            "avg": [[10000], [11000], [11500], [11999]],
            "deltaPercent": [[20], [27], [30], [33]],
            "lastUpdate": 7661998,
            "lightningEnd": 0,
        }
        deal = provider._parse_deal(raw)
        self.assertIsNotNone(deal)
        assert deal is not None
        self.assertEqual(deal.asin, "B00TEST123")
        self.assertEqual(deal.title, "Test Product")
        self.assertEqual(deal.current_price_cents, 7999)
        self.assertEqual(deal.reference_price_cents, 11999)
        self.assertEqual(deal.discount_percent, 33)
        self.assertTrue(deal.image_url.endswith("61k3Lay7JUL.jpg"))

    def test_query_is_for_amazon_es(self) -> None:
        config = make_config(source="keepa")
        query = KeepaProvider(config)._build_query(0)
        self.assertEqual(query["domainId"], 9)
        self.assertEqual(query["priceTypes"], [0])
        self.assertEqual(query["deltaPercentRange"], [25, 100])
        self.assertEqual(query["minRating"], 40)


class DatabaseTests(unittest.TestCase):
    def test_dedup_and_lower_price_resend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = DealDatabase(str(Path(tmp) / "test.sqlite3"))
            first = Deal("A", "Product", 10000, 14000, 29)
            self.assertTrue(db.should_send(first, 0, 24, 5))
            db.mark_sent(first, 0)
            self.assertFalse(db.should_send(first, 0, 24, 5))

            small_drop = Deal("A", "Product", 9700, 14000, 31)
            self.assertFalse(db.should_send(small_drop, 0, 24, 5))

            large_drop = Deal("A", "Product", 9000, 14000, 36)
            self.assertTrue(db.should_send(large_drop, 0, 24, 5))
            db.close()


class TelegramTests(unittest.TestCase):
    def test_affiliate_url_and_message(self) -> None:
        config = make_config(amazon_associate_tag="example-21", dry_run=False)
        notifier = TelegramNotifier(config)
        deal = Deal("B00ABC", "TV & Audio", 7999, 11999, 33)
        self.assertEqual(
            notifier.amazon_url(deal.asin),
            "https://www.amazon.es/dp/B00ABC?tag=example-21",
        )
        message = notifier.render_message(deal)
        self.assertIn("TV &amp; Audio", message)
        self.assertIn("79,99 EUR", message)
        self.assertIn("-33%", message)
        self.assertIn("Enlace de afiliado", message)


class ConfigTests(unittest.TestCase):
    def test_reject_non_spanish_domain(self) -> None:
        config = make_config(keepa_domain_id=3)
        with self.assertRaises(ValueError):
            config.validate(source_override="demo", dry_run_override=True)


if __name__ == "__main__":
    unittest.main()
