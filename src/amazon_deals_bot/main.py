from __future__ import annotations

import argparse
from dataclasses import replace
import logging
import re
import sys

from .config import Config
from .database import DealDatabase
from .demo import DEMO_HOT_ASIN, DemoProvider
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
    parser.add_argument("--test-telegram-public", action="store_true", help="Send one test message to the public Telegram channel")
    parser.add_argument("--test-telegram-personal", action="store_true", help="Send one test message to the personal Telegram chat")
    parser.add_argument("--demo-hot", action="store_true", help="Send a full personal HOT/restock demo alert without Keepa")
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

    telegram_action = args.test_telegram_public or args.test_telegram_personal or args.demo_hot
    validation_source = "demo" if telegram_action else source
    validation_dry_run = True if telegram_action else dry_run
    try:
        config.validate(source_override=validation_source, dry_run_override=validation_dry_run)
        if telegram_action and not config.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required for Telegram tests")
        if args.test_telegram_public and not config.telegram_public_chat_id:
            raise ValueError("TELEGRAM_PUBLIC_CHAT_ID is required for the public Telegram test")
        if (args.test_telegram_personal or args.demo_hot) and not config.telegram_personal_chat_id:
            raise ValueError("TELEGRAM_PERSONAL_CHAT_ID is required for personal/HOT Telegram tests")
    except ValueError as exc:
        logging.error("Configuration error: %s", exc)
        return 2

    if args.check_config:
        print(f"Configuration OK (source={source}, amazon=es, poll={config.poll_seconds}s, dry_run={dry_run})")
        return 0

    if args.test_telegram_public:
        TelegramNotifier(config).send_test(personal=False)
        print("Telegram public test sent successfully")
        return 0

    if args.test_telegram_personal:
        TelegramNotifier(config).send_test(personal=True)
        print("Telegram personal test sent successfully")
        return 0

    if args.demo_hot:
        return _run_demo_hot(config)

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


def _run_demo_hot(config: Config) -> int:
    demo_config = replace(config, restock_enabled=True, keepa_tracking_enabled=True)
    database = DealDatabase(":memory:")
    try:
        database.add_watch(DEMO_HOT_ASIN, Priority.HOT, personal=True)
        provider = DemoProvider(emit_hot_notification=True, hot_only=True)
        notifier = TelegramNotifier(demo_config)
        stats = MonitoringService(demo_config, provider, database, notifier, dry_run=False).run_once("restock")
        if stats["sent"] != 1 or stats["failed"]:
            logging.error("HOT demo did not complete successfully: %s", stats)
            return 1
        print("Personal HOT demo sent successfully")
        return 0
    finally:
        database.close()


def _validate_asin(value: str) -> str:
    asin = value.strip().upper()
    if not ASIN_RE.match(asin):
        raise ValueError("ASIN must contain exactly 10 letters/digits")
    return asin


if __name__ == "__main__":
    sys.exit(main())
