"""
webapp.py - Walmart Competitive Price Monitor Web Dashboard
Run with: start_web.bat  |  Access at: http://localhost:5050
"""

import asyncio
import json
import threading
import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

BASE_DIR = Path(__file__).parent
PRODUCTS_FILE = BASE_DIR / "products.json"
DB_FILE = BASE_DIR / "prices_db.json"

SCRAPE_INTERVAL_HOURS = 1  # Auto-check every hour

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_scrape_running = False
_last_run: str = "Never"
_last_run_summary: str = ""
_next_run_time: datetime | None = None


def _scheduler_loop():
    """Background thread: automatically check prices every hour."""
    global _next_run_time
    # Wait 2 minutes after startup before first auto-run
    _next_run_time = datetime.now() + timedelta(minutes=2)
    time.sleep(120)
    while True:
        if not _scrape_running:
            log.info("⏰ Scheduler: starting automatic price check...")
            _run_scrape_sync()
        _next_run_time = datetime.now() + timedelta(hours=SCRAPE_INTERVAL_HOURS)
        log.info(f"⏰ Scheduler: next auto-check at {_next_run_time.strftime('%I:%M %p')}")
        secs = max(60, (_next_run_time - datetime.now()).total_seconds())
        time.sleep(secs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_scheduler_loop, daemon=True)
    t.start()
    log.info(f"✅ Auto price monitor started — checks every {SCRAPE_INTERVAL_HOURS}h")
    yield


app = FastAPI(lifespan=lifespan)


def _load_json(path, default):
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _run_scrape_sync():
    global _scrape_running, _last_run, _last_run_summary
    try:
        asyncio.run(_do_scrape())
    except Exception as e:
        _last_run_summary = f"Error: {e}"
    finally:
        _scrape_running = False


async def _do_scrape():
    global _last_run, _last_run_summary
    from scraper import scrape_all_prices
    from emailer import send_price_alert

    products = _load_json(PRODUCTS_FILE, [])
    db = _load_json(DB_FILE, {})
    is_first_run = not any(not v.get("manual") for v in db.values())
    changes = []
    scraped = 0
    failed = 0

    for product in products:
        item_id = str(product["item_id"])
        product_name = product["product_name"]
        walmart_price = product.get("walmart_price")
        competitors = product.get("competitors", [])

        results = await scrape_all_prices(competitors)

        for result in results:
            retailer = result["retailer"]
            url = result["url"]
            new_price = result["price"]
            error = result.get("error")
            key = f"{item_id}|{retailer}"

            if new_price is None:
                failed += 1
                log.warning(f"  [{retailer}] skipped — {error or 'price not found'}")
                continue

            scraped += 1
            old_entry = db.get(key)
            old_price = old_entry["price"] if old_entry and not old_entry.get("manual") else None

            # Sanity check 1: price vs Walmart price — catches bot-redirect pages
            # returning completely unrelated product prices
            if walmart_price and walmart_price > 0:
                if new_price < walmart_price * 0.30:
                    log.warning(
                        f"  [{retailer}] Price ${new_price:.2f} is unrealistically"
                        f" below Walmart ${walmart_price:.2f} — likely bot-redirect, skipping"
                    )
                    failed += 1
                    continue

            # Sanity check 2: reject prices that moved too far from last stored value
            if old_price and old_price > 0:
                ratio = new_price / old_price
                if ratio < 0.5 or ratio > 4.0:
                    log.warning(f"  [{retailer}] Suspicious price ${new_price:.2f} vs stored ${old_price:.2f} — skipping")
                    failed += 1
                    continue

            db[key] = {
                "product_name": product_name,
                "item_id": item_id,
                "retailer": retailer,
                "url": url,
                "price": new_price,
                "manual": False,
                "last_updated": datetime.now().isoformat(),
            }

            if old_price is not None and not is_first_run:
                diff = new_price - old_price
                if abs(diff) >= 0.01:
                    changes.append({
                        "product_name": product_name, "item_id": item_id,
                        "retailer": retailer, "url": url,
                        "old_price": old_price, "new_price": new_price,
                        "diff": diff, "walmart_price": walmart_price,
                    })

    _save_json(DB_FILE, db)
    _last_run = datetime.now().strftime("%b %d, %Y %I:%M %p")

    # Sync to cloud in background (if env vars set)
    try:
        from cloud_store import save_db
        save_db(db)
    except Exception:
        pass

    if is_first_run:
        _last_run_summary = f"First run: {scraped} prices seeded."
    elif changes:
        send_price_alert(changes)
        _last_run_summary = f"{scraped} checked, {len(changes)} change(s) — email sent!"
    else:
        _last_run_summary = f"{scraped} checked, no changes. ({failed} sites unreachable)"


# ── API ────────────────────────────────────────────────────────────────────────

@app.get("/api/prices")
def get_prices():
    return JSONResponse(_load_json(DB_FILE, {}))


@app.get("/api/status")
def get_status():
    next_run_str = _next_run_time.strftime("%I:%M %p") if _next_run_time else "soon"
    return {
        "running": _scrape_running,
        "last_run": _last_run,
        "summary": _last_run_summary,
        "next_run": next_run_str,
    }


@app.post("/api/check")
def trigger_check():
    global _scrape_running
    if _scrape_running:
        return {"status": "already_running"}
    _scrape_running = True
    threading.Thread(target=_run_scrape_sync, daemon=True).start()
    return {"status": "started"}


@app.post("/api/manual_price")
async def manual_price(request: Request):
    """Save a manually-entered price. Triggers email if price changed."""
    body = await request.json()
    item_id = str(body["item_id"])
    retailer = body["retailer"]
    new_price = float(body["price"])
    url = body.get("url", "")

    products = _load_json(PRODUCTS_FILE, [])
    product = next((p for p in products if str(p["item_id"]) == item_id), {})
    product_name = product.get("product_name", "")
    walmart_price = product.get("walmart_price")

    db = _load_json(DB_FILE, {})
    key = f"{item_id}|{retailer}"
    old_entry = db.get(key)
    old_price = old_entry["price"] if old_entry else None

    db[key] = {
        "product_name": product_name,
        "item_id": item_id,
        "retailer": retailer,
        "url": url,
        "price": new_price,
        "manual": True,
        "last_updated": datetime.now().isoformat(),
    }
    _save_json(DB_FILE, db)

    # Send alert if price changed
    if old_price is not None and abs(new_price - old_price) >= 0.01:
        from emailer import send_price_alert
        send_price_alert([{
            "product_name": product_name, "item_id": item_id,
            "retailer": f"{retailer} (manual)", "url": url,
            "old_price": old_price, "new_price": new_price,
            "diff": new_price - old_price, "walmart_price": walmart_price,
        }])
        return {"status": "saved", "alert": "sent"}

    return {"status": "saved", "alert": "none"}


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    products = _load_json(PRODUCTS_FILE, [])
    all_retailers = ["Amazon", "B&H Photo", "Best Buy", "Costco", "Sam's Club", "Staples", "Target"]

    products_js = json.dumps({
        str(p["item_id"]): {
            "name": p["product_name"],
            "walmart": p.get("walmart_price"),
            "competitors": {c["name"]: c.get("url") or "" for c in p.get("competitors", [])}
        }
        for p in products
    })

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Walmart Competitive Price Monitor</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:Arial,sans-serif;background:#ede7f6;color:#333}}
    header{{background:#6a1b9a;color:#fff;padding:18px 32px;display:flex;align-items:center;gap:16px}}
    header h1{{font-size:20px;font-weight:700;color:#fff}}
    header .sub{{font-size:12px;opacity:.85;margin-top:2px;color:#fff}}
    .status-bar{{background:#f3e5f5;border-bottom:1px solid #ce93d8;padding:10px 32px;display:flex;align-items:center;gap:24px;font-size:13px;flex-wrap:wrap}}
    .dot{{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px}}
    .dot.idle{{background:#4caf50}}.dot.running{{background:#ff9800;animation:pulse 1s infinite}}
    @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
    #check-btn{{background:#6a1b9a;color:#fff;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:bold}}
    #check-btn:hover{{background:#4a148c}}
    #check-btn:disabled{{background:#ce93d8;cursor:not-allowed}}
    .container{{padding:24px 32px}}
    .product-card{{background:#fff;border-radius:10px;margin-bottom:24px;box-shadow:0 2px 8px rgba(74,20,140,.12);overflow:hidden}}
    .product-header{{background:#e1bee7;padding:14px 20px;display:flex;justify-content:space-between;align-items:center}}
    .product-header h2{{font-size:16px;color:#4a148c}}
    .item-id{{font-size:11px;color:#888;font-family:monospace}}
    .walmart-price{{font-size:14px;font-weight:bold;color:#4a148c}}
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    th{{padding:10px 16px;text-align:left;background:#f8f4fc;color:#6a1b9a;font-weight:600;border-bottom:2px solid #e1bee7}}
    td{{padding:10px 16px;border-bottom:1px solid #f3e5f5;vertical-align:middle}}
    tr:last-child td{{border-bottom:none}}
    tr:hover td{{background:#faf5ff}}
    .price{{font-weight:bold;font-size:14px}}
    .na{{color:#bbb;font-style:italic}}
    .manual-badge{{font-size:10px;background:#fff3cd;color:#856404;border:1px solid #ffc107;border-radius:4px;padding:1px 5px;margin-left:5px}}
    .updated{{font-size:11px;color:#999}}
    .retailer-link{{color:#6a1b9a;text-decoration:none}}
    .retailer-link:hover{{text-decoration:underline;color:#4a148c}}
    .badge-low{{color:#c62828;font-weight:bold}}
    .badge-high{{color:#2e7d32;font-weight:bold}}
    /* Manual entry */
    .manual-entry{{display:flex;align-items:center;gap:6px}}
    .manual-entry input{{width:90px;border:1px solid #ce93d8;border-radius:4px;padding:4px 8px;font-size:13px}}
    .manual-entry button{{background:#6a1b9a;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px}}
    .manual-entry button:hover{{background:#4a148c}}
    .toast{{position:fixed;bottom:24px;right:24px;background:#4a148c;color:#fff;padding:12px 20px;border-radius:8px;font-size:13px;display:none;z-index:999}}
    footer{{text-align:center;padding:20px;font-size:11px;color:#9c6baf}}
  </style>
</head>
<body>
<header>
  <div>
    <h1>&#127881; Walmart Competitive Price Monitor</h1>
    <div class="sub">AirPods product line &nbsp;|&nbsp; Auto-refreshes every 60 seconds</div>
  </div>
</header>

<div class="status-bar">
  <span><span class="dot idle" id="dot"></span><span id="status-text">Idle</span></span>
  <span>Last run: <strong id="last-run">—</strong></span>
  <span>Next auto-check: <strong id="next-run">—</strong></span>
  <span id="summary-text" style="color:#555"></span>
  <button id="check-btn" onclick="triggerCheck()">&#9654; Check Now</button>
</div>

<div class="container" id="content">
  <p style="color:#999;text-align:center;padding:40px">Loading…</p>
</div>

<div class="toast" id="toast"></div>

<footer>
  🤖 Auto-checks every hour automatically &nbsp;|&nbsp; Threshold: $0.01 change triggers email &nbsp;|&nbsp;
  <strong>✏️ Tip:</strong> For sites showing N/A, enter the price manually — changes will trigger email alerts.
</footer>

<script>
const PRODUCTS = {products_js};
const RETAILERS = {json.dumps(all_retailers)};

function showToast(msg, ok=true) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = ok ? '#2e7d32' : '#c62828';
  t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3000);
}}

function fmt(price, manual) {{
  if (price == null) return '<span class="na">N/A</span>';
  const badge = manual ? '<span class="manual-badge">✏️ manual</span>' : '';
  return '<span class="price">$' + price.toFixed(2) + '</span>' + badge;
}}

function vsWalmart(price, wm) {{
  if (!price || !wm) return '';
  const diff = price - wm;
  if (Math.abs(diff) < 0.01) return '<small style="color:#888">= Walmart</small>';
  const cls = diff < 0 ? 'badge-low' : 'badge-high';
  const sign = diff < 0 ? '▼' : '▲';
  return '<small class="' + cls + '">' + sign + ' $' + Math.abs(diff).toFixed(2) + ' vs Walmart</small>';
}}

function manualInput(itemId, retailer, url, currentPrice) {{
  const placeholder = currentPrice ? currentPrice.toFixed(2) : '0.00';
  return `<div class="manual-entry">
    <input type="number" step="0.01" min="0" placeholder="${{placeholder}}"
           id="inp_${{itemId}}_${{retailer.replace(/[^a-z]/gi,'_')}}" />
    <button onclick="saveManual('${{itemId}}','${{retailer}}','${{url}}')">Save</button>
  </div>`;
}}

async function saveManual(itemId, retailer, url) {{
  const key = 'inp_' + itemId + '_' + retailer.replace(/[^a-z]/gi,'_');
  const val = parseFloat(document.getElementById(key).value);
  if (!val || val <= 0) {{ showToast('Enter a valid price', false); return; }}
  const r = await fetch('/api/manual_price', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{item_id: itemId, retailer, price: val, url}})
  }});
  const data = await r.json();
  if (data.alert === 'sent') showToast('✅ Price saved & alert email sent!');
  else showToast('✅ Price saved');
  loadPrices();
}}

async function loadPrices() {{
  const [pr, sr] = await Promise.all([fetch('/api/prices'), fetch('/api/status')]);
  const db = await pr.json();
  const status = await sr.json();

  document.getElementById('last-run').textContent = status.last_run || '—';
  document.getElementById('next-run').textContent = status.running ? 'Running now…' : (status.next_run || '—');
  document.getElementById('summary-text').textContent = status.summary || '';
  const dot = document.getElementById('dot');
  const btn = document.getElementById('check-btn');
  if (status.running) {{
    dot.className = 'dot running';
    document.getElementById('status-text').textContent = 'Scraping…';
    btn.disabled = true; btn.textContent = '⏳ Running…';
  }} else {{
    dot.className = 'dot idle';
    document.getElementById('status-text').textContent = 'Idle';
    btn.disabled = false; btn.textContent = '▶ Check Now';
  }}

  let html = '';
  for (const [itemId, meta] of Object.entries(PRODUCTS)) {{
    const wm = meta.walmart;
    const wmStr = wm ? '$' + wm.toFixed(2) : 'OOS';
    html += `<div class="product-card">
      <div class="product-header">
        <div><h2>${{meta.name}}</h2><span class="item-id">Item ID: ${{itemId}}</span></div>
        <span class="walmart-price">Walmart.com: ${{wmStr}}</span>
      </div>
      <table><thead><tr>
        <th>Retailer</th><th>Current Price</th><th>vs Walmart</th><th>Last Updated</th><th>Update Price</th>
      </tr></thead><tbody>`;

    for (const retailer of RETAILERS) {{
      const key = itemId + '|' + retailer;
      const entry = db[key];
      const price = entry ? entry.price : null;
      const manual = entry ? entry.manual : false;
      const updated = entry ? new Date(entry.last_updated).toLocaleString() : '—';
      const url = (meta.competitors && meta.competitors[retailer]) || '';
      const rLabel = url
        ? `<a class="retailer-link" href="${{url}}" target="_blank">${{retailer}} ↗</a>`
        : retailer;

      html += `<tr>
        <td>${{rLabel}}</td>
        <td>${{fmt(price, manual)}}</td>
        <td>${{vsWalmart(price, wm)}}</td>
        <td class="updated">${{updated}}</td>
        <td>${{manualInput(itemId, retailer, url, price)}}</td>
      </tr>`;
    }}
    html += '</tbody></table></div>';
  }}
  document.getElementById('content').innerHTML = html;
}}

async function triggerCheck() {{
  await fetch('/api/check', {{method: 'POST'}});
  loadPrices();
}}

loadPrices();
setInterval(loadPrices, 60000);
</script>
</body>
</html>""")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5050, log_level="warning")
