from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Deal, Priority, ProductSnapshot, ProductState, WatchItem


class DealDatabase:
    def __init__(self, path: str):
        self.path = Path(path) if path != ":memory:" else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sent_deals (
                asin TEXT NOT NULL,
                price_type INTEGER NOT NULL,
                last_price_cents INTEGER NOT NULL,
                last_discount_percent INTEGER NOT NULL,
                last_sent_at TEXT NOT NULL,
                PRIMARY KEY (asin, price_type)
            );

            CREATE TABLE IF NOT EXISTS products (
                asin TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                last_state TEXT NOT NULL,
                last_price_cents INTEGER,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                root_category INTEGER,
                tracking_since TEXT,
                listed_since TEXT,
                release_date TEXT
            );

            CREATE TABLE IF NOT EXISTS sent_events (
                event_key TEXT PRIMARY KEY,
                asin TEXT NOT NULL,
                state TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asin TEXT NOT NULL,
                state TEXT NOT NULL,
                price_cents INTEGER,
                recorded_at TEXT NOT NULL,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                asin TEXT PRIMARY KEY,
                priority TEXT NOT NULL,
                personal INTEGER NOT NULL DEFAULT 1,
                tracking_synced INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS processed_notifications (
                notification_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def should_send_deal(self, deal: Deal, price_type: int, cooldown_hours: float, min_extra_discount_percent: float) -> bool:
        row = self.connection.execute(
            "SELECT * FROM sent_deals WHERE asin = ? AND price_type = ?", (deal.asin, price_type)
        ).fetchone()
        if row is None:
            return True
        old_price = int(row["last_price_cents"])
        if deal.current_price_cents >= old_price:
            return False
        price_drop_percent = ((old_price - deal.current_price_cents) / old_price) * 100.0
        if price_drop_percent >= min_extra_discount_percent:
            return True
        last_sent = datetime.fromisoformat(row["last_sent_at"])
        if last_sent.tzinfo is None:
            last_sent = last_sent.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last_sent >= timedelta(hours=cooldown_hours)

    # Backwards-compatible alias used by the original v0.1 tests/API.
    should_send = should_send_deal

    def mark_deal_sent(self, deal: Deal, price_type: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """
            INSERT INTO sent_deals (asin, price_type, last_price_cents, last_discount_percent, last_sent_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(asin, price_type) DO UPDATE SET
                last_price_cents = excluded.last_price_cents,
                last_discount_percent = excluded.last_discount_percent,
                last_sent_at = excluded.last_sent_at
            """,
            (deal.asin, price_type, deal.current_price_cents, deal.discount_percent, now),
        )
        self.connection.commit()

    mark_sent = mark_deal_sent

    def get_product_state(self, asin: str) -> ProductState | None:
        row = self.connection.execute("SELECT last_state FROM products WHERE asin = ?", (asin,)).fetchone()
        return ProductState(row["last_state"]) if row else None

    def is_known_product(self, asin: str) -> bool:
        return self.connection.execute("SELECT 1 FROM products WHERE asin = ?", (asin,)).fetchone() is not None

    def upsert_product(self, product: ProductSnapshot, state: ProductState | None = None) -> ProductState | None:
        previous = self.get_product_state(product.asin)
        now = datetime.now(timezone.utc).isoformat()
        state = state or product.natural_state
        self.connection.execute(
            """
            INSERT INTO products (
                asin, title, last_state, last_price_cents, first_seen_at, last_seen_at,
                root_category, tracking_since, listed_since, release_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asin) DO UPDATE SET
                title = excluded.title,
                last_state = excluded.last_state,
                last_price_cents = excluded.last_price_cents,
                last_seen_at = excluded.last_seen_at,
                root_category = excluded.root_category,
                tracking_since = COALESCE(excluded.tracking_since, products.tracking_since),
                listed_since = COALESCE(excluded.listed_since, products.listed_since),
                release_date = COALESCE(excluded.release_date, products.release_date)
            """,
            (
                product.asin,
                product.title,
                state.value,
                product.current_price_cents,
                now,
                now,
                product.root_category,
                product.tracking_since.isoformat() if product.tracking_since else None,
                product.listed_since.isoformat() if product.listed_since else None,
                product.release_date.isoformat() if product.release_date else None,
            ),
        )
        if previous != state:
            self.record_state(product.asin, state, product.current_price_cents, {"title": product.title})
        self.connection.commit()
        return previous

    def record_state(self, asin: str, state: ProductState, price_cents: int | None = None, metadata: dict | None = None) -> None:
        self.connection.execute(
            "INSERT INTO state_history(asin, state, price_cents, recorded_at, metadata_json) VALUES (?, ?, ?, ?, ?)",
            (asin, state.value, price_cents, datetime.now(timezone.utc).isoformat(), json.dumps(metadata or {}, ensure_ascii=False)),
        )
        self.connection.commit()

    def event_was_sent(self, event_key: str) -> bool:
        return self.connection.execute("SELECT 1 FROM sent_events WHERE event_key = ?", (event_key,)).fetchone() is not None

    def mark_event_sent(self, event_key: str, asin: str, state: ProductState, metadata: dict | None = None) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO sent_events(event_key, asin, state, sent_at, metadata_json) VALUES (?, ?, ?, ?, ?)",
            (event_key, asin, state.value, datetime.now(timezone.utc).isoformat(), json.dumps(metadata or {}, ensure_ascii=False)),
        )
        self.connection.commit()

    def add_watch(self, asin: str, priority: Priority = Priority.HOT, personal: bool = True) -> None:
        self.connection.execute(
            """
            INSERT INTO watchlist(asin, priority, personal, tracking_synced, created_at)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(asin) DO UPDATE SET priority = excluded.priority, personal = excluded.personal, tracking_synced = 0
            """,
            (asin.upper(), priority.value, int(personal), datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()

    def remove_watch(self, asin: str) -> None:
        self.connection.execute("DELETE FROM watchlist WHERE asin = ?", (asin.upper(),))
        self.connection.commit()

    def list_watchlist(self, only_unsynced: bool = False) -> list[WatchItem]:
        sql = "SELECT asin, priority, personal, tracking_synced FROM watchlist"
        if only_unsynced:
            sql += " WHERE tracking_synced = 0"
        sql += " ORDER BY created_at"
        return [
            WatchItem(row["asin"], Priority(row["priority"]), bool(row["personal"]), bool(row["tracking_synced"]))
            for row in self.connection.execute(sql).fetchall()
        ]

    def mark_tracking_synced(self, asin: str) -> None:
        self.connection.execute("UPDATE watchlist SET tracking_synced = 1 WHERE asin = ?", (asin.upper(),))
        self.connection.commit()

    def notification_processed(self, notification_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM processed_notifications WHERE notification_id = ?", (notification_id,)
        ).fetchone() is not None

    def mark_notification_processed(self, notification_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO processed_notifications(notification_id, processed_at) VALUES (?, ?)",
            (notification_id, datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()

    def get_int_setting(self, key: str, default: int = 0) -> int:
        row = self.connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        try:
            return int(row["value"]) if row else default
        except (TypeError, ValueError):
            return default

    def set_setting(self, key: str, value: str | int) -> None:
        self.connection.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        self.connection.commit()

    def expire_stale_products(self, stale_hours: int) -> int:
        if stale_hours <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
        rows = self.connection.execute(
            "SELECT asin, last_seen_at, last_state, last_price_cents FROM products WHERE last_state != ?",
            (ProductState.EXPIRED.value,),
        ).fetchall()
        count = 0
        for row in rows:
            seen = datetime.fromisoformat(row["last_seen_at"])
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            if seen >= cutoff:
                continue
            self.connection.execute(
                "UPDATE products SET last_state = ? WHERE asin = ?",
                (ProductState.EXPIRED.value, row["asin"]),
            )
            self.record_state(row["asin"], ProductState.EXPIRED, row["last_price_cents"], {"reason": "stale"})
            count += 1
        self.connection.commit()
        return count

    def close(self) -> None:
        self.connection.close()
