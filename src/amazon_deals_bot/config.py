from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "si"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else int(raw)


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else float(raw)


def _int_list(name: str) -> tuple[int, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    return tuple(int(part.strip()) for part in raw.split(",") if part.strip())


def _str_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class Config:
    source: str
    keepa_api_key: str
    keepa_domain_id: int
    keepa_price_type: int
    keepa_date_range: int
    keepa_max_pages: int
    min_discount_percent: int
    min_price_eur: float
    max_price_eur: float
    min_rating: float
    only_lowest_90: bool
    must_have_amazon_offer: bool
    include_categories: tuple[int, ...]
    exclude_categories: tuple[int, ...]
    title_exclude_words: tuple[str, ...]
    max_deals_per_cycle: int
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_send_image: bool
    telegram_disable_notification: bool
    amazon_associate_tag: str
    affiliate_disclosure: str
    poll_seconds: int
    resend_cooldown_hours: float
    resend_min_extra_discount_percent: float
    db_path: str
    http_timeout_seconds: int
    log_level: str
    dry_run: bool

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Config":
        load_dotenv(env_file)
        return cls(
            source=os.getenv("SOURCE", "keepa").strip().lower(),
            keepa_api_key=os.getenv("KEEPA_API_KEY", "").strip(),
            keepa_domain_id=_int("KEEPA_DOMAIN_ID", 9),
            keepa_price_type=_int("KEEPA_PRICE_TYPE", 0),
            keepa_date_range=_int("KEEPA_DATE_RANGE", 0),
            keepa_max_pages=_int("KEEPA_MAX_PAGES", 1),
            min_discount_percent=_int("MIN_DISCOUNT_PERCENT", 25),
            min_price_eur=_float("MIN_PRICE_EUR", 5.0),
            max_price_eur=_float("MAX_PRICE_EUR", 1500.0),
            min_rating=_float("MIN_RATING", 4.0),
            only_lowest_90=_bool("ONLY_LOWEST_90", False),
            must_have_amazon_offer=_bool("MUST_HAVE_AMAZON_OFFER", True),
            include_categories=_int_list("INCLUDE_CATEGORIES"),
            exclude_categories=_int_list("EXCLUDE_CATEGORIES"),
            title_exclude_words=_str_list("TITLE_EXCLUDE_WORDS"),
            max_deals_per_cycle=_int("MAX_DEALS_PER_CYCLE", 20),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
            telegram_send_image=_bool("TELEGRAM_SEND_IMAGE", False),
            telegram_disable_notification=_bool("TELEGRAM_DISABLE_NOTIFICATION", False),
            amazon_associate_tag=os.getenv("AMAZON_ASSOCIATE_TAG", "").strip(),
            affiliate_disclosure=os.getenv("AFFILIATE_DISCLOSURE", "Enlace de afiliado").strip(),
            poll_seconds=_int("POLL_SECONDS", 600),
            resend_cooldown_hours=_float("RESEND_COOLDOWN_HOURS", 24.0),
            resend_min_extra_discount_percent=_float("RESEND_MIN_EXTRA_DISCOUNT_PERCENT", 5.0),
            db_path=os.getenv("DB_PATH", "data/deals.sqlite3").strip(),
            http_timeout_seconds=_int("HTTP_TIMEOUT_SECONDS", 20),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            dry_run=_bool("DRY_RUN", False),
        )

    def validate(self, source_override: str | None = None, dry_run_override: bool | None = None) -> None:
        source = (source_override or self.source).lower()
        dry_run = self.dry_run if dry_run_override is None else dry_run_override

        if source not in {"keepa", "demo"}:
            raise ValueError("SOURCE must be 'keepa' or 'demo'")
        if source == "keepa" and not self.keepa_api_key:
            raise ValueError("KEEPA_API_KEY is required when SOURCE=keepa")
        if not dry_run and (not self.telegram_bot_token or not self.telegram_chat_id):
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required unless DRY_RUN=true")
        if self.keepa_domain_id != 9:
            raise ValueError("This version is intentionally restricted to Amazon.es (KEEPA_DOMAIN_ID=9)")
        if self.keepa_date_range not in {0, 1, 2, 3}:
            raise ValueError("KEEPA_DATE_RANGE must be 0, 1, 2 or 3")
        if self.keepa_max_pages < 1:
            raise ValueError("KEEPA_MAX_PAGES must be >= 1")
        if not (0 <= self.min_discount_percent <= 100):
            raise ValueError("MIN_DISCOUNT_PERCENT must be between 0 and 100")
        if not (0 <= self.min_rating <= 5):
            raise ValueError("MIN_RATING must be between 0 and 5")
        if self.poll_seconds < 60:
            raise ValueError("POLL_SECONDS must be >= 60")
        if self.max_deals_per_cycle < 1:
            raise ValueError("MAX_DEALS_PER_CYCLE must be >= 1")
