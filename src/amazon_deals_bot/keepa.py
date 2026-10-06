from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from .config import Config
from .http import post_json
from .models import Deal

LOGGER = logging.getLogger(__name__)
_TAG_RE = re.compile(r"<[^>]+>")


class KeepaProvider:
    ENDPOINT = "https://api.keepa.com/deal"

    def __init__(self, config: Config):
        self.config = config

    def fetch_deals(self) -> list[Deal]:
        deals: list[Deal] = []
        for page in range(self.config.keepa_max_pages):
            query = self._build_query(page)
            url = f"{self.ENDPOINT}?key={quote_plus(self.config.keepa_api_key)}"
            data = post_json(url, query, self.config.http_timeout_seconds)
            if data.get("error"):
                raise RuntimeError(f"Keepa error: {data['error']}")

            raw_deals = data.get("deals", {}).get("dr", [])
            LOGGER.info(
                "Keepa page=%s returned=%s tokens_left=%s tokens_consumed=%s",
                page,
                len(raw_deals),
                data.get("tokensLeft"),
                data.get("tokensConsumed"),
            )
            for raw in raw_deals:
                deal = self._parse_deal(raw)
                if deal is not None:
                    deals.append(deal)

            if len(raw_deals) < 150:
                break
        return deals

    def _build_query(self, page: int) -> dict[str, Any]:
        min_price = max(0, round(self.config.min_price_eur * 100))
        max_price = max(min_price, round(self.config.max_price_eur * 100))
        query: dict[str, Any] = {
            "page": page,
            "domainId": self.config.keepa_domain_id,
            "priceTypes": [self.config.keepa_price_type],
            "dateRange": self.config.keepa_date_range,
            "isRangeEnabled": True,
            "isFilterEnabled": True,
            "currentRange": [min_price, max_price],
            "deltaPercentRange": [self.config.min_discount_percent, 100],
            "minRating": round(self.config.min_rating * 10) if self.config.min_rating > 0 else -1,
            "isLowest": False,
            "isLowest90": self.config.only_lowest_90,
            "isLowestOffer": False,
            "isOutOfStock": False,
            "isBackInStock": False,
            "hasReviews": self.config.min_rating > 0,
            "filterErotic": True,
            "singleVariation": True,
            "isRisers": False,
            "mustHaveAmazonOffer": self.config.must_have_amazon_offer,
            "sortType": 4,
        }
        if self.config.include_categories:
            query["includeCategories"] = list(self.config.include_categories)
        if self.config.exclude_categories:
            query["excludeCategories"] = list(self.config.exclude_categories)
        return query

    def _parse_deal(self, raw: dict[str, Any]) -> Deal | None:
        price_type = self.config.keepa_price_type
        date_range = self.config.keepa_date_range
        try:
            current = int(raw["current"][price_type])
            if current <= 0:
                return None

            averages = raw.get("avg") or []
            reference = None
            if len(averages) > date_range and len(averages[date_range]) > price_type:
                value = int(averages[date_range][price_type])
                reference = value if value > 0 else None

            percentages = raw.get("deltaPercent") or []
            discount = 0
            if len(percentages) > date_range and len(percentages[date_range]) > price_type:
                discount = max(0, int(percentages[date_range][price_type]))

            title = html.unescape(_TAG_RE.sub("", str(raw.get("title", "")).strip()))
            if not title:
                title = raw["asin"]

            image_url = None
            image_codes = raw.get("image") or []
            if image_codes:
                image_name = "".join(chr(int(code)) for code in image_codes)
                if image_name:
                    image_url = f"https://images-na.ssl-images-amazon.com/images/I/{image_name}"

            return Deal(
                asin=str(raw["asin"]),
                title=title,
                current_price_cents=current,
                reference_price_cents=reference,
                discount_percent=discount,
                image_url=image_url,
                root_category=int(raw["rootCat"]) if raw.get("rootCat") is not None else None,
                source_updated_at=_keepa_time(raw.get("lastUpdate")),
                lightning_end=_keepa_time(raw.get("lightningEnd")) if raw.get("lightningEnd") else None,
            )
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            LOGGER.warning("Skipping malformed Keepa deal: %s", exc)
            return None


def _keepa_time(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    unix_seconds = (minutes + 21_564_000) * 60
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
