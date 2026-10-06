from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from ..config import Config
from ..http import get_json, post_json
from ..models import Deal, ProductSnapshot, ProductState

LOGGER = logging.getLogger(__name__)
_TAG_RE = re.compile(r"<[^>]+>")
KEEPA_EPOCH_MINUTES = 21_564_000


@dataclass(frozen=True, slots=True)
class KeepaTrackingNotification:
    notification_id: str
    asin: str
    title: str
    state: ProductState
    current_price_cents: int | None
    image_url: str | None
    create_date: int


class KeepaProvider:
    BASE_URL = "https://api.keepa.com"

    def __init__(self, config: Config):
        self.config = config

    # ----------------------------- Deals -----------------------------
    def fetch_deals(self) -> list[Deal]:
        return self._fetch_deal_pages(back_in_stock=False)

    def fetch_restock_deals(self) -> list[Deal]:
        return self._fetch_deal_pages(back_in_stock=True)

    def _fetch_deal_pages(self, back_in_stock: bool) -> list[Deal]:
        deals: list[Deal] = []
        for page in range(self.config.keepa_max_pages):
            query = self._build_deal_query(page, back_in_stock=back_in_stock)
            data = post_json(
                f"{self.BASE_URL}/deal",
                query,
                self.config.http_timeout_seconds,
                params={"key": self.config.keepa_api_key},
            )
            self._check_error(data)
            raw_deals = data.get("deals", {}).get("dr", [])
            self._log_tokens("deal-restock" if back_in_stock else "deal", data, len(raw_deals))
            for raw in raw_deals:
                deal = self._parse_deal(raw)
                if deal is not None:
                    deals.append(deal)
            if len(raw_deals) < 150:
                break
        return deals

    def _build_deal_query(self, page: int, back_in_stock: bool = False) -> dict[str, Any]:
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
            "deltaPercentRange": [0 if back_in_stock else self.config.min_discount_percent, 100],
            "minRating": round(self.config.min_rating * 10) if self.config.min_rating > 0 else -1,
            "isLowest": False,
            "isLowest90": False if back_in_stock else self.config.only_lowest_90,
            "isLowestOffer": False,
            "isOutOfStock": False,
            "isBackInStock": back_in_stock,
            "hasReviews": self.config.min_rating > 0,
            "filterErotic": True,
            "singleVariation": True,
            "isRisers": False,
            "mustHaveAmazonOffer": self.config.must_have_amazon_offer,
            "sortType": 4,
        }
        categories = self.config.discovery_root_categories if back_in_stock else self.config.include_categories
        if categories:
            query["includeCategories"] = list(categories)
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
            return Deal(
                asin=str(raw["asin"]),
                title=_clean_title(raw.get("title"), str(raw["asin"])),
                current_price_cents=current,
                reference_price_cents=reference,
                discount_percent=discount,
                image_url=_decode_deal_image(raw.get("image")),
                root_category=_positive_int(raw.get("rootCat")),
                source_updated_at=keepa_time_to_datetime(raw.get("lastUpdate")),
                lightning_end=keepa_time_to_datetime(raw.get("lightningEnd")),
            )
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            LOGGER.warning("Skipping malformed Keepa deal: %s", exc)
            return None

    # --------------------------- Discovery ---------------------------
    def discover_new_products(self) -> list[ProductSnapshot]:
        since = keepa_now_minutes() - self.config.discovery_lookback_minutes
        selection: dict[str, Any] = {
            "trackingSince_gte": since,
            "singleVariation": True,
            "perPage": self.config.discovery_per_page,
            "sort": [["trackingSince", "desc"]],
        }
        if self.config.discovery_root_categories:
            selection["rootCategory"] = list(self.config.discovery_root_categories)
        asins = self._query_asins(selection, self.config.discovery_max_pages)
        return self.fetch_products(asins)

    def discover_preorders(self) -> list[ProductSnapshot]:
        since = keepa_now_minutes() - self.config.preorder_lookback_minutes
        selection: dict[str, Any] = {
            "buyBoxIsPreorder": True,
            "lastOffersUpdate_gte": since,
            "singleVariation": True,
            "perPage": self.config.discovery_per_page,
            "sort": [["lastOffersUpdate", "desc"]],
        }
        if self.config.discovery_root_categories:
            selection["rootCategory"] = list(self.config.discovery_root_categories)
        asins = self._query_asins(selection, self.config.discovery_max_pages)
        return self.fetch_products(asins)

    def _query_asins(self, selection: dict[str, Any], max_pages: int) -> list[str]:
        results: list[str] = []
        per_page = int(selection.get("perPage", 50))
        for page in range(max_pages):
            payload = dict(selection)
            payload["page"] = page
            data = post_json(
                f"{self.BASE_URL}/query",
                payload,
                self.config.http_timeout_seconds,
                params={"domain": self.config.keepa_domain_id, "key": self.config.keepa_api_key},
            )
            self._check_error(data)
            page_asins = [str(x) for x in data.get("asinList", []) if x]
            results.extend(page_asins)
            self._log_tokens("query", data, len(page_asins))
            if len(page_asins) < per_page:
                break
        # Preserve order while removing duplicates.
        return list(dict.fromkeys(results))

    def fetch_products(self, asins: Iterable[str]) -> list[ProductSnapshot]:
        unique = list(dict.fromkeys(a.upper() for a in asins if a))
        products: list[ProductSnapshot] = []
        for start in range(0, len(unique), 100):
            batch = unique[start : start + 100]
            if not batch:
                continue
            data = get_json(
                f"{self.BASE_URL}/product",
                {
                    "key": self.config.keepa_api_key,
                    "domain": self.config.keepa_domain_id,
                    "asin": ",".join(batch),
                    "history": 0,
                    "update": self.config.keepa_product_update_hours,
                    "stats": 1,
                },
                self.config.http_timeout_seconds,
            )
            self._check_error(data)
            raw_products = data.get("products", [])
            self._log_tokens("product", data, len(raw_products))
            for raw in raw_products:
                parsed = self._parse_product(raw)
                if parsed is not None:
                    products.append(parsed)
        return products

    def _parse_product(self, raw: dict[str, Any]) -> ProductSnapshot | None:
        asin = str(raw.get("asin") or "").strip()
        if not asin:
            return None
        stats = raw.get("stats") or {}
        current_values = stats.get("current") or []
        current_price: int | None = None
        if len(current_values) > self.config.keepa_price_type:
            current_price = _positive_int(current_values[self.config.keepa_price_type])
        availability = _int_or_none(raw.get("availabilityAmazon"))
        is_preorder = bool(raw.get("buyBoxIsPreorder")) or availability == 1
        return ProductSnapshot(
            asin=asin,
            title=_clean_title(raw.get("title"), asin),
            current_price_cents=current_price,
            image_url=_product_image(raw),
            root_category=_positive_int(raw.get("rootCategory")),
            tracking_since=keepa_time_to_datetime(raw.get("trackingSince")),
            listed_since=keepa_time_to_datetime(raw.get("listedSince")),
            release_date=keepa_time_to_datetime(raw.get("releaseDate")),
            source_updated_at=keepa_time_to_datetime(raw.get("lastUpdate")),
            availability_amazon=availability,
            is_preorder=is_preorder,
            is_amazon_offer=(current_price is not None or availability in {0, 1, 3, 4}),
        )

    # ------------------------ Keepa Tracking -------------------------
    def add_stock_tracking(self, asin: str, metadata: str = "amazon-deals-telegram") -> None:
        tracking = {
            "asin": asin.upper(),
            "ttl": 0,
            "expireNotify": False,
            "desiredPricesInMainCurrency": True,
            "mainDomainId": self.config.keepa_domain_id,
            "updateInterval": self.config.keepa_tracking_update_hours,
            "metaData": metadata[:500],
            "thresholdValues": [],
            "notifyIf": [
                {"domain": self.config.keepa_domain_id, "csvType": self.config.keepa_price_type, "notifyIfType": 0},
                {"domain": self.config.keepa_domain_id, "csvType": self.config.keepa_price_type, "notifyIfType": 1},
            ],
            "notificationType": [False, False, False, False, False, True, False],
            "individualNotificationInterval": -1,
        }
        data = post_json(
            f"{self.BASE_URL}/tracking",
            [tracking],
            self.config.http_timeout_seconds,
            params={"key": self.config.keepa_api_key, "type": "add"},
        )
        self._check_error(data)
        self._log_tokens("tracking-add", data, 1)

    def remove_stock_tracking(self, asin: str) -> None:
        data = get_json(
            f"{self.BASE_URL}/tracking",
            {"key": self.config.keepa_api_key, "type": "remove", "asin": asin.upper()},
            self.config.http_timeout_seconds,
        )
        self._check_error(data)

    def fetch_tracking_notifications(self, since: int) -> list[KeepaTrackingNotification]:
        data = get_json(
            f"{self.BASE_URL}/tracking",
            {"key": self.config.keepa_api_key, "type": "notification", "since": max(0, since), "revise": 0},
            self.config.http_timeout_seconds,
        )
        self._check_error(data)
        raw_notifications = data.get("notifications") or data.get("notification") or []
        if isinstance(raw_notifications, dict):
            raw_notifications = [raw_notifications]
        out: list[KeepaTrackingNotification] = []
        for raw in raw_notifications:
            cause = _int_or_none(raw.get("trackingNotificationCause"))
            if cause not in {4, 5}:
                continue
            prices = raw.get("currentPrices") or []
            price = _positive_int(prices[self.config.keepa_price_type]) if len(prices) > self.config.keepa_price_type else None
            image_name = str(raw.get("image") or "").strip()
            out.append(
                KeepaTrackingNotification(
                    notification_id=str(raw.get("notificationId") or f"{raw.get('asin')}:{raw.get('createDate')}:{cause}"),
                    asin=str(raw.get("asin") or ""),
                    title=_clean_title(raw.get("title"), str(raw.get("asin") or "Amazon product")),
                    state=ProductState.OUT_OF_STOCK if cause == 4 else ProductState.BACK_IN_STOCK,
                    current_price_cents=price,
                    image_url=f"https://images-na.ssl-images-amazon.com/images/I/{image_name}" if image_name else None,
                    create_date=int(raw.get("createDate") or 0),
                )
            )
        self._log_tokens("tracking-notification", data, len(out))
        return out

    @staticmethod
    def _check_error(data: dict[str, Any]) -> None:
        if data.get("error"):
            raise RuntimeError(f"Keepa error: {data['error']}")

    @staticmethod
    def _log_tokens(operation: str, data: dict[str, Any], count: int) -> None:
        LOGGER.info(
            "Keepa op=%s results=%s tokens_left=%s tokens_consumed=%s refill_rate=%s",
            operation,
            count,
            data.get("tokensLeft"),
            data.get("tokensConsumed"),
            data.get("refillRate"),
        )


def keepa_now_minutes() -> int:
    return int(time.time() // 60) - KEEPA_EPOCH_MINUTES


def keepa_time_to_datetime(value: Any) -> datetime | None:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    return datetime.fromtimestamp((minutes + KEEPA_EPOCH_MINUTES) * 60, tz=timezone.utc)


def _clean_title(value: Any, fallback: str) -> str:
    text = html.unescape(_TAG_RE.sub("", str(value or "")).strip())
    return text or fallback


def _decode_deal_image(value: Any) -> str | None:
    if not value:
        return None
    try:
        name = "".join(chr(int(code)) for code in value)
    except (TypeError, ValueError):
        return None
    return f"https://images-na.ssl-images-amazon.com/images/I/{name}" if name else None


def _product_image(raw: dict[str, Any]) -> str | None:
    images = str(raw.get("imagesCSV") or "").split(",")
    first = images[0].strip() if images else ""
    if not first:
        return None
    return f"https://images-na.ssl-images-amazon.com/images/I/{first}"


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
