from __future__ import annotations

import argparse
import logging
import re
import sys

from .config import Config
from .database import DealDatabase
from .demo import DemoProvider
from .models import Priority
from .providers.keepa import KeepaProvider
from .service import MonitoringService
from .telegram import TelegramNotifier

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Amazon.es monitor: deals, new products, preorders and restocks -> Telegram")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not send Telegram messages")
    parser.add_argument("--source", choices=["keepa", "demo"], help="Override SOURCE")
    parser.add_argument("--mode", choices=["all", "deals", "discovery", "preorders", "restock"], default="all")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument("--check-config", action="store_true", help="Validate config and exit")
    parser.add_argument("--watch-asin", help="Add an ASIN to the HOT/watch list")
    parser.add_argument("--watch-priority", choices=[x.value for x in Priority], default=Priority.HOT.value)
    parser.add_argument("--public-watch", action="store_true", help="Send watch alerts to public channel instead of personal chat")
    parser.add_argument("--unwatch-asin", help="Remove an ASIN from the watch list")
    parser.add_argument("--list-watchlist", action="store_true", help="List locally watched ASINs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.from_env(args.env_file)
    source = args.source or config.source
    dry_run = args.dry_run or config.dry_run

    logging.basicConfig(level=getattr(logging, config.log_level, logging.INFO), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    try:
        config.validate(source_override=source, dry_run_override=dry_run)
    except ValueError as exc:
        logging.error("Configuration error: %s", exc)
        return 2

    if args.check_config:
        print(f"Configuration OK (source={source}, amazon=es, poll={config.poll_seconds}s, dry_run={dry_run})")
        return 0

    provider = KeepaProvider(config) if source == "keepa" else DemoProvider()
    database = DealDatabase(config.db_path)
    try:
        if args.list_watchlist:
            for item in database.list_watchlist():
                print(f"{item.asin}\t{item.priority.value}\tpersonal={item.personal}\ttracking_synced={item.tracking_synced}")
            return 0

        if args.watch_asin:
            asin = _validate_asin(args.watch_asin)
            priority = Priority(args.watch_priority)
            personal = not args.public_watch
            database.add_watch(asin, priority, personal)
            if source == "keepa" and config.keepa_tracking_enabled:
                provider.add_stock_tracking(asin, metadata=f"amazon-deals-telegram|{priority.value}|personal={int(personal)}")
                database.mark_tracking_synced(asin)
            print(f"Watching {asin} priority={priority.value} personal={personal}")
            return 0

        if args.unwatch_asin:
            asin = _validate_asin(args.unwatch_asin)
            database.remove_watch(asin)
            if source == "keepa" and config.keepa_tracking_enabled:
                try:
                    provider.remove_stock_tracking(asin)
                except Exception:
                    logging.exception("Local watch removed, but Keepa tracking removal failed for %s", asin)
            print(f"Stopped watching {asin}")
            return 0

        notifier = None if dry_run else TelegramNotifier(config)
        service = MonitoringService(config, provider, database, notifier, dry_run)
        if args.once:
            service.run_once(args.mode)
        else:
            service.run_forever(args.mode)
    except KeyboardInterrupt:
        logging.info("Stopped by user")
    finally:
        database.close()
    return 0


def _validate_asin(value: str) -> str:
    asin = value.strip().upper()
    if not ASIN_RE.match(asin):
        raise ValueError("ASIN must contain exactly 10 letters/digits")
    return asin


if __name__ == "__main__":
    sys.exit(main())
