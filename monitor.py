"""
monitor.py - Walmart Competitive Price Monitor
----------------------------------------------
Run this script directly (e.g. via Windows Task Scheduler every hour).
On first run it seeds the price database and sends NO emails.
On subsequent runs it compares current prices against stored prices and
emails the team if any price moved by >= $0.01.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from scraper import scrape_all_prices
from emailer import send_price_alert

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
PRODUCTS_FILE = BASE_DIR / "products.json"
DB_FILE = BASE_DIR / "prices_db.json"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ── Logging ────────────────────────────────────────────────────────────────────
log_file = LOG_DIR / f"monitor_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-7s]  %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
PRICE_THRESHOLD = 0.01  # minimum price difference (USD) that triggers an alert


# ── Helpers ────────────────────────────────────────────────────────────────────
def _load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            log.warning(f"Corrupt JSON at {path}, starting fresh.")
    return default


def _save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _db_key(item_id: str, retailer: str) -> str:
    return f"{item_id}|{retailer}"


# ── Core ───────────────────────────────────────────────────────────────────────
async def run() -> None:
    log.info("=" * 60)
    log.info("Walmart Competitive Price Monitor — run started")
    log.info("=" * 60)

    products: list[dict] = _load_json(PRODUCTS_FILE, [])
    if not products:
        log.error(f"No products found in {PRODUCTS_FILE}. Exiting.")
        return

    db: dict = _load_json(DB_FILE, {})
    is_first_run = len(db) == 0

    if is_first_run:
        log.info("First run detected — prices will be seeded; no alerts sent today.")

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
            new_price: float | None = result["price"]
            error: str | None = result.get("error")
            key = _db_key(item_id, retailer)

            if new_price is None:
                log.warning(f"  [{retailer}] scrape failed — {error}")
                continue

            old_entry = db.get(key)
            old_price: float | None = old_entry["price"] if old_entry else None

            # Sanity check 1: price vs Walmart price — catches bot-redirect pages
            if walmart_price and walmart_price > 0:
                if new_price < walmart_price * 0.30:
                    log.warning(
                        f"  [{retailer}] Price ${new_price:.2f} is unrealistically"
                        f" below Walmart ${walmart_price:.2f} — likely bot-redirect, skipping"
                    )
                    continue

            # Sanity check 2: reject prices that moved too far from last stored value
            if old_price and old_price > 0:
                ratio = new_price / old_price
                if ratio < 0.5 or ratio > 4.0:
                    log.warning(f"  [{retailer}] Suspicious price ${new_price:.2f} vs stored ${old_price:.2f} — skipping (possible scrape error)")
                    continue

            # Update database
            db[key] = {
                "product_name": product_name,
                "item_id": item_id,
                "retailer": retailer,
                "url": url,
                "price": new_price,
                "last_updated": datetime.now().isoformat(),
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
                changes.append(
                    {
                        "product_name": product_name,
                        "item_id": item_id,
                        "retailer": retailer,
                        "url": url,
                        "old_price": old_price,
                        "new_price": new_price,
                        "diff": diff,
                        "walmart_price": walmart_price,
                    }
                )
            else:
                log.info(f"  [{retailer}] ${new_price:.2f}  (no change)")

    # Persist updated prices locally
    _save_json(DB_FILE, db)
    log.info(f"\nDatabase saved → {DB_FILE}")

    # Sync to cloud (only if JSONBIN_KEY + JSONBIN_ID env vars are set)
    try:
        from cloud_store import save_db
        save_db(db)
        log.info("Prices synced to cloud database ✓")
    except Exception as e:
        log.warning(f"Cloud sync skipped: {e}")

    # Send alerts
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
