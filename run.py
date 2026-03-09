#!/usr/bin/env python3
"""
Main entry point.
Usage:
  python run.py            # scrape + generate page
  python run.py --debug    # scrape with API response dump + generate page
  python run.py --generate # only regenerate the HTML page (no scraping)
"""

import argparse
import logging
import os
import sys
from datetime import datetime

# Ensure all relative paths resolve from the project directory,
# regardless of the working directory (e.g. when run from cron).
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

# Configure logging
log_dir = os.getenv("LOG_DIR", "./logs")
os.makedirs(log_dir, exist_ok=True)

log_file = os.path.join(
    log_dir, f"run_{datetime.now().strftime('%Y%m%d')}.log"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("run")


def main():
    parser = argparse.ArgumentParser(description="Used cars monitor")
    parser.add_argument("--debug", action="store_true",
                        help="Dump captured API responses to logs/ for inspection")
    parser.add_argument("--generate", action="store_true",
                        help="Only regenerate HTML page, skip scraping")
    parser.add_argument("--rerate", action="store_true",
                        help="Force re-running AI ratings for all cars, ignoring cache")
    args = parser.parse_args()

    if args.generate:
        logger.info("Regenerating HTML page (no scraping)")
        from generate import generate
        output = generate(rerate=args.rerate)
        logger.info(f"Done. Page at: {output}")
        return

    target_url = os.getenv("TARGET_URL")
    if not target_url:
        logger.error(
            "TARGET_URL is not set. Copy .env.example to .env and fill it in."
        )
        sys.exit(1)

    logger.info(f"=== Run started at {datetime.now().isoformat()} ===")
    logger.info(f"Target: {target_url}")

    # Scrape
    from scraper import run_scrape
    cars = run_scrape(target_url, debug=args.debug)

    if not cars:
        logger.warning("No vehicles found — check the debug dump or verify the URL")
    else:
        logger.info(f"Scraped {len(cars)} vehicles")

    # Update database
    from db import upsert_cars
    summary = upsert_cars(cars)
    logger.info(
        f"DB update: {summary['new']} new, "
        f"{summary['price_changed']} price changes, "
        f"{summary['disappeared']} disappeared, "
        f"{summary['unchanged']} unchanged"
    )

    # Generate HTML
    from generate import generate
    output = generate(rerate=args.rerate)
    logger.info(f"Page generated: {output}")
    logger.info("=== Run complete ===")


if __name__ == "__main__":
    main()
