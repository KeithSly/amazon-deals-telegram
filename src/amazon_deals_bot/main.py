from __future__ import annotations

import argparse
import logging
import sys

from .config import Config
from .database import DealDatabase
from .demo import DemoProvider
from .keepa import KeepaProvider
from .service import DealService
from .telegram import TelegramNotifier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Amazon.es deal detector -> Telegram")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not send Telegram messages")
    parser.add_argument("--source", choices=["keepa", "demo"], help="Override SOURCE")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument("--check-config", action="store_true", help="Validate config and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.from_env(args.env_file)
    source = args.source or config.source
    dry_run = args.dry_run or config.dry_run

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    try:
        config.validate(source_override=source, dry_run_override=dry_run)
    except ValueError as exc:
        logging.error("Configuration error: %s", exc)
        return 2

    if args.check_config:
        print(
            "Configuration OK "
            f"(source={source}, domain=amazon.es, min_discount={config.min_discount_percent}%, "
            f"poll={config.poll_seconds}s, dry_run={dry_run})"
        )
        return 0

    provider = KeepaProvider(config) if source == "keepa" else DemoProvider()
    database = DealDatabase(config.db_path)
    notifier = None if dry_run else TelegramNotifier(config)
    service = DealService(config, provider, database, notifier, dry_run)

    try:
        if args.once:
            service.run_once()
        else:
            service.run_forever()
    except KeyboardInterrupt:
        logging.info("Stopped by user")
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
