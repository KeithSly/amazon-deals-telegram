from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Deal


class DealDatabase:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_deals (
                asin TEXT NOT NULL,
                price_type INTEGER NOT NULL,
                last_price_cents INTEGER NOT NULL,
                last_discount_percent INTEGER NOT NULL,
                last_sent_at TEXT NOT NULL,
                PRIMARY KEY (asin, price_type)
            )
            """
        )
        self.connection.commit()

    def should_send(
        self,
        deal: Deal,
        price_type: int,
        cooldown_hours: float,
        min_extra_discount_percent: float,
    ) -> bool:
        row = self.connection.execute(
            "SELECT * FROM sent_deals WHERE asin = ? AND price_type = ?",
            (deal.asin, price_type),
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

    def mark_sent(self, deal: Deal, price_type: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """
            INSERT INTO sent_deals (
                asin, price_type, last_price_cents, last_discount_percent, last_sent_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(asin, price_type) DO UPDATE SET
                last_price_cents = excluded.last_price_cents,
                last_discount_percent = excluded.last_discount_percent,
                last_sent_at = excluded.last_sent_at
            """,
            (deal.asin, price_type, deal.current_price_cents, deal.discount_percent, now),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
