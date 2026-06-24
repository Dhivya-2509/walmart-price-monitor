"""
monitor_cloud.py - Cloud price scraper (one-shot run).
Called by Render Cron Job every hour.

Scrapes all competitor sites → compares with JSONBin DB → saves changes → sends email.

Required env vars (set in Render → Environment):
  JSONBIN_KEY         — JSONBin Master Key
  JSONBIN_ID          — JSONBin Bin ID
  GMAIL_USER          — Gmail address used to send alerts
  GMAIL_APP_PASSWORD  — Gmail App Password (16-char)
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from scraper_cloud import scrape_all_prices
from emailer_cloud import send_price_alert
from cloud_store import load_db, save_db

BASE_DIR = Path(__file__).parent
PRODUCTS_FILE = BASE_DIR / "products.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-7s]  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

PRICE_THRESHOLD = 0.01


def _load_products() -> list:
    if PRODUCTS_FILE.exists():
        with open(PRODUCTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


async def run() -> None:
    log.info("=" * 60)
    log.info("Walmart Price Monitor (Cloud) — run started")
    log.info("=" * 60)

    products = _load_products()
    if not products:
        log.error(f"No products found in {PRODUCTS_FILE}. Exiting.")
        return

    db = load_db()
    is_first_run = len(db) == 0

    if is_first_run:
        log.info("First run — prices will be seeded; no alerts sent today.")

    changes: list[dict] = []

    for product in products:
        item_id = str(product["item_id"])
        product_name = product["product_name"]
        walmart_price = product.get("walmart_price")

        log.info(f"\nProduct: {product_name}  (ID: {item_id})")

        competitors = product.get("competitors", [])
        results = await scrape_all_prices(competitors)

        for result in results:
            retailer: str = result["retailer"]
            url: str = result["url"]
            new_price = result["price"]
            error = result.get("error")
            key = f"{item_id}|{retailer}"

            if new_price is None:
                log.warning(f"  [{retailer}] scrape failed — {error}")
                continue

            old_entry = db.get(key)
            old_price = old_entry["price"] if old_entry else None

            # Sanity check: reject implausible price swings (likely scrape errors)
            if old_price and old_price > 0:
                ratio = new_price / old_price
                if ratio < 0.5 or ratio > 4.0:
                    log.warning(
                        f"  [{retailer}] Suspicious ${new_price:.2f} vs stored "
                        f"${old_price:.2f} — skipping"
                    )
                    continue

            db[key] = {
                "product_name": product_name,
                "item_id": item_id,
                "retailer": retailer,
                "url": url,
                "price": new_price,
                "manual": False,
                "last_updated": datetime.utcnow().isoformat(),
            }

            if old_price is None:
                log.info(f"  [{retailer}] seeded ${new_price:.2f}")
                continue

            diff = new_price - old_price
            if abs(diff) >= PRICE_THRESHOLD:
                direction = "▼ down" if diff < 0 else "▲ up"
                log.info(
                    f"  [{retailer}] ${old_price:.2f} → ${new_price:.2f}  "
                    f"({direction} ${abs(diff):.2f})  *** ALERT ***"
                )
                changes.append({
                    "product_name": product_name,
                    "item_id": item_id,
                    "retailer": retailer,
                    "url": url,
                    "old_price": old_price,
                    "new_price": new_price,
                    "diff": diff,
                    "walmart_price": walmart_price,
                })
            else:
                log.info(f"  [{retailer}] ${new_price:.2f}  (no change)")

    save_db(db)
    log.info("\nPrices saved to JSONBin cloud database ✓")

    if is_first_run:
        log.info("First run complete. Next hourly run will start sending alerts.")
    elif changes:
        log.info(f"\nSending alert email for {len(changes)} change(s)…")
        send_price_alert(changes)
    else:
        log.info("\nNo price changes detected. No email sent.")

    log.info("=" * 60)
    log.info("Run complete")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(run())
