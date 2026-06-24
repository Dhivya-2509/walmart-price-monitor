"""
webapp_cloud.py - Cloud dashboard (read-only viewer).
Deploy to Render.com as a Web Service.
Prices are updated hourly by the Render Cron Job (monitor_cloud.py).

Required env vars on Render:
  JSONBIN_KEY  — JSONBin Master Key
  JSONBIN_ID   — JSONBin Bin ID
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from cloud_store import load_db, save_db

BASE_DIR = Path(__file__).parent
PRODUCTS_FILE = BASE_DIR / "products.json"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI()


def _load_products():
    if PRODUCTS_FILE.exists():
        with open(PRODUCTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


# ── API ────────────────────────────────────────────────────────────────────────

@app.get("/api/prices")
def get_prices():
    return JSONResponse(load_db())


@app.get("/api/status")
def get_status():
    db = load_db()
    # Find the most recent last_updated across all entries
    last_run = "Never"
    if db:
        timestamps = [v.get("last_updated", "") for v in db.values() if v.get("last_updated")]
        if timestamps:
            latest = max(timestamps)
            try:
                dt = datetime.fromisoformat(latest)
                last_run = dt.strftime("%b %d, %Y %I:%M %p UTC")
            except Exception:
                last_run = latest

    total = len(db)
    return {
        "running": False,
        "last_run": last_run,
        "summary": f"Prices checked hourly from cloud. {total} entries in database.",
        "next_run": "Auto (hourly cron)",
    }


@app.post("/api/manual_price")
async def manual_price(request: Request):
    """Save a manually-entered price to the cloud database."""
    body = await request.json()
    item_id = str(body["item_id"])
    retailer = body["retailer"]
    new_price = float(body["price"])
    url = body.get("url", "")

    products = _load_products()
    product = next((p for p in products if str(p["item_id"]) == item_id), {})
    product_name = product.get("product_name", "")

    db = load_db()
    key = f"{item_id}|{retailer}"
    db[key] = {
        "product_name": product_name,
        "item_id": item_id,
        "retailer": retailer,
        "url": url,
        "price": new_price,
        "manual": True,
        "last_updated": datetime.utcnow().isoformat(),
    }
    save_db(db)
    return {"status": "saved"}


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    products = _load_products()
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
    header h1{{font-size:20px;font-weight:700}}
    header .sub{{font-size:12px;opacity:.8;margin-top:2px}}
    .cloud-badge{{background:#ffc220;color:#6a1b9a;font-size:11px;font-weight:bold;padding:3px 10px;border-radius:12px;margin-left:10px}}
    .status-bar{{background:#f3e5f5;border-bottom:1px solid #ce93d8;padding:10px 32px;display:flex;align-items:center;gap:24px;font-size:13px;flex-wrap:wrap}}
    .dot{{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px;background:#4caf50}}
    .container{{padding:24px 32px}}
    .product-card{{background:#fff;border-radius:10px;margin-bottom:24px;box-shadow:0 2px 8px rgba(106,27,154,.12);overflow:hidden}}
    .product-header{{background:#f3e5f5;padding:14px 20px;display:flex;justify-content:space-between;align-items:center}}
    .product-header h2{{font-size:16px;color:#6a1b9a}}
    .item-id{{font-size:11px;color:#888;font-family:monospace}}
    .walmart-price{{font-size:14px;font-weight:bold;color:#6a1b9a}}
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    th{{padding:10px 16px;text-align:left;background:#f9f9f9;color:#666;font-weight:600;border-bottom:2px solid #e0e0e0}}
    td{{padding:10px 16px;border-bottom:1px solid #f0f0f0;vertical-align:middle}}
    tr:last-child td{{border-bottom:none}}
    tr:hover td{{background:#fafafa}}
    .price{{font-weight:bold;font-size:14px}}
    .na{{color:#bbb;font-style:italic}}
    .manual-badge{{font-size:10px;background:#fff3cd;color:#856404;border:1px solid #ffc107;border-radius:4px;padding:1px 5px;margin-left:5px}}
    .updated{{font-size:11px;color:#999}}
    .retailer-link{{color:#6a1b9a;text-decoration:none}}
    .retailer-link:hover{{text-decoration:underline}}
    .badge-low{{color:#c62828;font-weight:bold}}
    .badge-high{{color:#2e7d32;font-weight:bold}}
    .manual-entry{{display:flex;align-items:center;gap:6px}}
    .manual-entry input{{width:90px;border:1px solid #ddd;border-radius:4px;padding:4px 8px;font-size:13px}}
    .manual-entry button{{background:#6a1b9a;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px}}
    .manual-entry button:hover{{background:#4a148c}}
    .toast{{position:fixed;bottom:24px;right:24px;background:#323232;color:#fff;padding:12px 20px;border-radius:8px;font-size:13px;display:none;z-index:999}}
    footer{{text-align:center;padding:20px;font-size:11px;color:#888}}
  </style>
</head>
<body>
<header>
  <div>
    <h1>&#127881; Walmart Competitive Price Monitor <span class="cloud-badge">&#9729; CLOUD</span></h1>
    <div class="sub">AirPods product line &nbsp;|&nbsp; Prices updated hourly automatically</div>
  </div>
</header>

<div class="status-bar">
  <span><span class="dot"></span>Live</span>
  <span id="summary-text" style="color:#555">Loading prices…</span>
  <span id="last-run-text" style="font-size:12px;color:#888"></span>
  <span style="font-size:12px;color:#888">Auto-refreshes every 60 seconds</span>
</div>

<div class="container" id="content">
  <p style="color:#999;text-align:center;padding:40px">Loading…</p>
</div>

<div class="toast" id="toast"></div>

<footer>
  &#9729; Cloud Dashboard &nbsp;|&nbsp; Prices checked hourly &nbsp;|&nbsp; Threshold: $0.01 &nbsp;|&nbsp;
  <strong>&#9998; Tip:</strong> For sites showing N/A, enter the price manually.
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
  const badge = manual ? '<span class="manual-badge">&#9998; manual</span>' : '';
  return '<span class="price">$' + price.toFixed(2) + '</span>' + badge;
}}

function vsWalmart(price, wm) {{
  if (!price || !wm) return '';
  const diff = price - wm;
  if (Math.abs(diff) < 0.01) return '<small style="color:#888">= Walmart</small>';
  const cls = diff < 0 ? 'badge-low' : 'badge-high';
  const sign = diff < 0 ? '&#9660;' : '&#9650;';
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
  await r.json();
  showToast('Price saved');
  loadPrices();
}}

async function loadPrices() {{
  const [pr, sr] = await Promise.all([fetch('/api/prices'), fetch('/api/status')]);
  const db = await pr.json();
  const status = await sr.json();
  document.getElementById('summary-text').textContent = status.summary || '';
  if (status.last_run && status.last_run !== 'Never') {{
    document.getElementById('last-run-text').textContent = 'Last checked: ' + status.last_run;
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
        ? `<a class="retailer-link" href="${{url}}" target="_blank">${{retailer}} &#8599;</a>`
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

loadPrices();
setInterval(loadPrices, 60000);
</script>
</body>
</html>""")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
