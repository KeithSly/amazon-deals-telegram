from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ProductState(StrEnum):
    NEW = "NEW"
    PREORDER = "PREORDER"
    AVAILABLE = "AVAILABLE"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    BACK_IN_STOCK = "BACK_IN_STOCK"
    DEAL = "DEAL"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class AlertKind(StrEnum):
    DEAL = "deal"
    NEW_PRODUCT = "new_product"
    PREORDER = "preorder"
    RESTOCK = "restock"
    OUT_OF_STOCK = "out_of_stock"


class Priority(StrEnum):
    NORMAL = "NORMAL"
    NEW_RELEASE = "NEW_RELEASE"
    HOT = "HOT"
    RESTOCK = "RESTOCK"


@dataclass(frozen=True, slots=True)
class Deal:
    asin: str
    title: str
    current_price_cents: int
    reference_price_cents: int | None
    discount_percent: int
    image_url: str | None = None
    root_category: int | None = None
    source_updated_at: datetime | None = None
    lightning_end: datetime | None = None

    @property
    def current_price_eur(self) -> float:
        return self.current_price_cents / 100.0

    @property
    def reference_price_eur(self) -> float | None:
        if self.reference_price_cents is None:
            return None
        return self.reference_price_cents / 100.0


@dataclass(frozen=True, slots=True)
class ProductSnapshot:
    asin: str
    title: str
    current_price_cents: int | None = None
    image_url: str | None = None
    root_category: int | None = None
    tracking_since: datetime | None = None
    listed_since: datetime | None = None
    release_date: datetime | None = None
    source_updated_at: datetime | None = None
    availability_amazon: int | None = None
    is_preorder: bool = False
    is_amazon_offer: bool | None = None

    @property
    def current_price_eur(self) -> float | None:
        if self.current_price_cents is None:
            return None
        return self.current_price_cents / 100.0

    @property
    def natural_state(self) -> ProductState:
        if self.is_preorder or self.availability_amazon == 1:
            return ProductState.PREORDER
        if self.availability_amazon == 0:
            return ProductState.AVAILABLE
        if self.current_price_cents is not None and self.current_price_cents > 0:
            return ProductState.AVAILABLE
        if self.availability_amazon in {-1, 2, 3, 4}:
            return ProductState.OUT_OF_STOCK
        return ProductState.UNKNOWN


@dataclass(frozen=True, slots=True)
class Alert:
    kind: AlertKind
    state: ProductState
    product: ProductSnapshot
    priority: Priority = Priority.NORMAL
    deal: Deal | None = None
    personal: bool = False
    notification_id: str | None = None

    @property
    def event_key(self) -> str:
        price = self.product.current_price_cents or 0
        suffix = self.notification_id or ""
        target = "personal" if self.personal else "public"
        return f"{self.kind.value}:{self.product.asin}:{self.state.value}:{price}:{suffix}:{target}"


@dataclass(frozen=True, slots=True)
class WatchItem:
    asin: str
    priority: Priority
    personal: bool = True
    tracking_synced: bool = False
