"""
emailer.py - Sends price-change alerts via the signed-in Outlook desktop app
             using win32com (no SMTP credentials required).
"""

import logging
from datetime import datetime

log = logging.getLogger(__name__)

RECIPIENTS = [
    "Dhivya.N@walmart.com",
    "Kishore.Shathem@walmart.com",
    "Ashwini.Ragupathi@walmart.com",
    "Pattem.Bhavani@walmart.com",
]


def _format_walmart_price(price) -> str:
    if price is None:
        return "OOS / N/A"
    try:
        return f"${float(price):.2f}"
    except (ValueError, TypeError):
        return str(price)


def _build_html(changes: list[dict]) -> str:
    rows = ""
    for c in changes:
        diff = c["new_price"] - c["old_price"]
        color = "#c62828" if diff < 0 else "#2e7d32"
        arrow = "&#9660;" if diff < 0 else "&#9650;"  # ▼ or ▲
        direction = "decreased" if diff < 0 else "increased"
        diff_str = f"{arrow} ${abs(diff):.2f} ({direction})"

        wm_price = _format_walmart_price(c.get("walmart_price"))
        if c.get("walmart_price") is not None:
            gap = c["new_price"] - float(c["walmart_price"])
            vs = f"{'above' if gap > 0 else 'below'} Walmart by ${abs(gap):.2f}"
            wm_cell = f"{wm_price}<br><small style='color:#555'>{vs}</small>"
        else:
            wm_cell = wm_price

        rows += f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #e8e8e8;">
            {c['product_name']}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #e8e8e8;font-family:monospace;">
            {c['item_id']}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #e8e8e8;">
            <a href="{c['url']}" style="color:#0071ce;text-decoration:none;">{c['retailer']}</a>
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #e8e8e8;">${c['old_price']:.2f}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #e8e8e8;font-weight:bold;">
            ${c['new_price']:.2f}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #e8e8e8;color:{color};font-weight:bold;">
            {diff_str}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #e8e8e8;">{wm_cell}</td>
        </tr>"""

    now = datetime.now().strftime("%B %d, %Y  %I:%M %p CST")
    count = len(changes)
    noun = "change" if count == 1 else "changes"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;font-family:Arial,Helvetica,sans-serif;background:#f4f4f4;">
  <div style="max-width:960px;margin:auto;background:#fff;border-radius:8px;
              box-shadow:0 2px 8px rgba(0,0,0,0.12);overflow:hidden;">

    <!-- Header -->
    <div style="background:#0071ce;padding:22px 28px;">
      <h2 style="color:#fff;margin:0;font-size:20px;">
        &#128276; Competitive Price Change Alert
      </h2>
      <p style="color:#cde8ff;margin:6px 0 0;font-size:13px;">
        {count} price {noun} detected &nbsp;|&nbsp; {now}
      </p>
    </div>

    <!-- Table -->
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#f0f4f8;color:#444;">
            <th style="padding:12px 14px;text-align:left;border-bottom:2px solid #ddd;">Product</th>
            <th style="padding:12px 14px;text-align:left;border-bottom:2px solid #ddd;">Item ID</th>
            <th style="padding:12px 14px;text-align:left;border-bottom:2px solid #ddd;">Retailer</th>
            <th style="padding:12px 14px;text-align:left;border-bottom:2px solid #ddd;">Old Price</th>
            <th style="padding:12px 14px;text-align:left;border-bottom:2px solid #ddd;">New Price</th>
            <th style="padding:12px 14px;text-align:left;border-bottom:2px solid #ddd;">Change</th>
            <th style="padding:12px 14px;text-align:left;border-bottom:2px solid #ddd;">Walmart.com</th>
          </tr>
        </thead>
        <tbody>{rows}
        </tbody>
      </table>
    </div>

    <!-- Footer -->
    <div style="padding:16px 28px;background:#fafafa;border-top:1px solid #e8e8e8;">
      <p style="margin:0;font-size:11px;color:#888;">
        Automated alert from the Walmart Competitive Price Monitor &nbsp;|&nbsp;
        Checks every hour &nbsp;|&nbsp; Threshold: any change &ge; $0.01<br>
        To add/remove recipients or update products, edit
        <code>price_monitor/emailer.py</code> and <code>price_monitor/products.json</code>.
      </p>
    </div>

  </div>
</body>
</html>"""


def send_price_alert(changes: list[dict]) -> None:
    """Send a formatted HTML email via Outlook desktop (win32com)."""
    try:
        import win32com.client  # type: ignore

        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = olMailItem

        mail.To = "; ".join(RECIPIENTS)
        mail.Subject = (
            f"[Price Alert] {len(changes)} Competitor Price Change(s) Detected"
        )
        mail.HTMLBody = _build_html(changes)
        mail.Send()

        log.info(f"Email sent to: {', '.join(RECIPIENTS)}")

    except ImportError:
        log.error(
            "pywin32 is not installed.  Run:  pip install pywin32\n"
            "Then run:  python -m win32com.client.makepy"
        )
    except Exception as exc:
        log.error(f"Failed to send email: {exc}")
