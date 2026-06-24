"""
emailer_cloud.py - Sends price-change alerts via Gmail SMTP.
Used on Render.com (no Outlook/Windows COM available).

Required env vars:
  GMAIL_USER          — your Gmail address (e.g. walmart.pricebot@gmail.com)
  GMAIL_APP_PASSWORD  — 16-char Gmail App Password (not your login password)

To create a Gmail App Password:
  1. Go to myaccount.google.com → Security → 2-Step Verification (enable it)
  2. Search "App passwords" → select "Mail" → generate
  3. Copy the 16-char code (spaces optional) as GMAIL_APP_PASSWORD
"""

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

RECIPIENTS = [
    "Dhivya.N@walmart.com",
    "Kishore.Shathem@walmart.com",
    "Ashwini.Ragupathi@walmart.com",
    "Pattem.Bhavani@walmart.com",
]

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


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
        arrow = "&#9660;" if diff < 0 else "&#9650;"
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
            <a href="{c['url']}" style="color:#6a1b9a;text-decoration:none;">{c['retailer']}</a>
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

    now = datetime.utcnow().strftime("%B %d, %Y  %I:%M %p UTC")
    count = len(changes)
    noun = "change" if count == 1 else "changes"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;font-family:Arial,Helvetica,sans-serif;background:#f4f4f4;">
  <div style="max-width:960px;margin:auto;background:#fff;border-radius:8px;
              box-shadow:0 2px 8px rgba(0,0,0,0.12);overflow:hidden;">

    <div style="background:#6a1b9a;padding:22px 28px;">
      <h2 style="color:#fff;margin:0;font-size:20px;">
        &#128276; Competitive Price Change Alert
      </h2>
      <p style="color:#e1bee7;margin:6px 0 0;font-size:13px;">
        {count} price {noun} detected &nbsp;|&nbsp; {now}
      </p>
    </div>

    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#f3e5f5;color:#444;">
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

    <div style="padding:16px 28px;background:#fafafa;border-top:1px solid #e8e8e8;">
      <p style="margin:0;font-size:11px;color:#888;">
        Automated alert from the Walmart Competitive Price Monitor (Cloud) &nbsp;|&nbsp;
        Checks every hour &nbsp;|&nbsp; Threshold: any change &ge; $0.01<br>
        Powered by Render.com &nbsp;|&nbsp; Prices stored in JSONBin cloud database.
      </p>
    </div>

  </div>
</body>
</html>"""


def send_price_alert(changes: list[dict]) -> None:
    """Send a formatted HTML email via Gmail SMTP."""
    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")

    if not gmail_user or not gmail_pass:
        log.error(
            "GMAIL_USER and GMAIL_APP_PASSWORD env vars are required for cloud email. "
            "Set them in Render → Environment."
        )
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Price Alert] {len(changes)} Competitor Price Change(s) Detected"
    msg["From"] = gmail_user
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(_build_html(changes), "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(gmail_user, gmail_pass.replace(" ", ""))
            server.sendmail(gmail_user, RECIPIENTS, msg.as_string())
        log.info(f"Email sent to: {', '.join(RECIPIENTS)}")
    except smtplib.SMTPAuthenticationError:
        log.error(
            "Gmail authentication failed. Make sure you are using an App Password "
            "(not your Gmail login password). See instructions in emailer_cloud.py."
        )
    except Exception as exc:
        log.error(f"Failed to send email: {exc}")
