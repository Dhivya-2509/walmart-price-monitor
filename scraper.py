"""
scraper.py - Price scraper using real Chrome with user profile.
Uses your actual Chrome installation + profile (cookies/session) to bypass
bot detection and corporate SSL proxy — same as opening in your browser.

NOTE: Chrome must be fully closed before running a scrape.
"""

import asyncio
import random
import re
import logging
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger(__name__)

PRICE_REGEX = re.compile(r"\$?([\d,]+\.\d{2})")
_AMAZON_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")

CHROME_PATH = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
CHROME_PROFILE = r"C:\Users\d0n07ev\AppData\Local\Google\Chrome\User Data"

# ── Site-specific CSS selectors ────────────────────────────────────────────────
SITE_SELECTORS: dict[str, list[str]] = {
    "bhphotovideo.com": [
        '[data-selenium="pricingPrice"]',
        '[class*="price_salePrice"]',
        '[class*="price_Price"]',
    ],
    "amazon.com": [
        # Specific buy-box selectors only — no broad '.a-price .a-offscreen'
        # (that picks up prices from "Frequently bought together" on bot-redirect pages)
        '.a-price.apexPriceToPay .a-offscreen',
        '.a-price.priceToPay .a-offscreen',
        '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
        '#apex_desktop_newAccordionRow .a-price .a-offscreen',
        '[data-feature-name="apex_desktop"] .a-price .a-offscreen',
        '#buybox .a-price .a-offscreen',
        '#price_inside_buybox',
        '#priceblock_ourprice',
        '#priceblock_dealprice',
        '.priceToPay .a-offscreen',
        '.a-price[data-a-size="xl"] .a-offscreen',  # XL = buy box size
        # REMOVED: '.a-price[data-a-size="b"] .a-offscreen' — too broad
        # REMOVED: '.a-price .a-offscreen' — way too broad, picks up wrong prices from bot pages
    ],
    "bestbuy.com": [
        '[class*="priceView-customer-price"] span:first-child',
        '.priceView-hero-price span:first-child',
        '[data-testid="customer-price"] span',
    ],
    "target.com": [
        '[data-test="product-price"]',
        '[class*="styles__CurrentPriceFontSize"]',
        'span[class*="h-text-bs"]',
    ],
    "samsclub.com": [
        '[data-testid="product-price"]',
        '[class*="sc-price-display"]',
        '[itemprop="price"]',
    ],
    "staples.com": [
        '[itemprop="price"]',
        '[class*="lower-price"]',
        '.sku-now-price',
        '#priceDisplay .price-block',
    ],
    "costco.com": [
        # Verified via live DOM inspection 2026-06-24:
        # Price is split across child spans inside these data-testid containers
        '[data-testid="single-price-content"]',  # "$148.99" — most reliable
        '[data-testid="price"]',                  # same content, outer wrapper
        # Legacy fallbacks kept in case page structure changes
        '.your-price .value',
        '[automation-id="product-price"]',
        '.pricing-price .value',
        '[itemprop="price"]',
    ],
    "camelcamelcamel.com": [
        # Verified via live DOM inspection 2026-06-24:
        # Main buy-box current Amazon price (excludes hidden used/3rd-party span.smaller.bgp)
        'span.bgp:not(.smaller)',
        # Current price from Amazon price history table row
        'tr.pt.amazon.on td:nth-child(4)',
    ],
}


def _parse_price(text) -> float | None:
    if text is None:
        return None
    m = PRICE_REGEX.search(str(text).strip())
    if m:
        try:
            val = float(m.group(1).replace(",", ""))
            return val if 1.0 < val < 10000.0 else None
        except ValueError:
            return None
    return None


def _price_from_source(text: str) -> float | None:
    for pat in [
        r'"current_retail"\s*:\s*([\d.]+)',
        r'"currentRetail"\s*:\s*([\d.]+)',   # Target
        r'"currentPrice"\s*:\s*([\d.]+)',
        r'"offerPrice"\s*:\s*([\d.]+)',       # Target
        r'"salePrice"\s*:\s*([\d.]+)',
        r'"finalPrice"\s*:\s*([\d.]+)',
        r'"lowestPrice"\s*:\s*([\d.]+)',
        r'"discountedPrice"\s*:\s*([\d.]+)',
        r'"customerPrice"\s*:\s*([\d.]+)',    # Best Buy
        r'"price"\s*:\s*"?([\d.]+)"?',
        r'"listPrice"\s*:\s*([\d.]+)',        # fallback — pre-sale/regular price
        r'"regularPrice"\s*:\s*([\d.]+)',     # fallback — pre-sale/regular price
    ]:
        m = re.search(pat, text)
        if m:
            try:
                val = float(m.group(1))
                if 1.0 < val < 10000.0:
                    return val
            except ValueError:
                continue
    return None


async def _extract_price(page, url: str) -> float | None:
    hostname = urlparse(url).hostname or ""

    # 1. Site-specific CSS selectors
    for domain, selectors in SITE_SELECTORS.items():
        if domain in hostname:
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        text = await loc.text_content(timeout=4000)
                        price = _parse_price(text)
                        if price:
                            return price
                        for attr in ["content", "aria-label", "data-price"]:
                            val = await loc.get_attribute(attr, timeout=2000)
                            price = _parse_price(val)
                            if price:
                                return price
                except Exception:
                    continue
            break

    # 2. JSON-LD
    try:
        scripts = page.locator('script[type="application/ld+json"]')
        count = await scripts.count()
        for i in range(min(count, 5)):
            t = await scripts.nth(i).text_content(timeout=2000)
            if t and "price" in t.lower():
                p = _price_from_source(t)
                if p:
                    return p
    except Exception:
        pass

    # 2b. Next.js __NEXT_DATA__ (Target, Best Buy, etc.)
    try:
        nd = page.locator("script#__NEXT_DATA__").first
        if await nd.count() > 0:
            t = await nd.text_content(timeout=3000)
            if t:
                p = _price_from_source(t)
                if p:
                    return p
    except Exception:
        pass

    # 3. Meta price tags
    for sel in ['meta[property="product:price:amount"]', 'meta[itemprop="price"]']:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                val = await loc.get_attribute("content", timeout=2000)
                p = _parse_price(val)
                if p:
                    return p
        except Exception:
            continue

    # 4. Raw page source
    try:
        return _price_from_source(await page.content())
    except Exception:
        return None


async def _scrape_one(context, competitor: dict, semaphore: asyncio.Semaphore) -> dict:
    retailer = competitor["name"]
    url = competitor.get("url") or ""
    result = {"retailer": retailer, "url": url, "price": None, "error": None}

    if not url:
        result["error"] = "No URL"
        return result

    # Amazon: redirect to CamelCamelCamel to get live prices without bot detection
    actual_url = url
    if "amazon.com" in (urlparse(url).hostname or ""):
        m = _AMAZON_ASIN_RE.search(url)
        if m:
            actual_url = f"https://camelcamelcamel.com/product/{m.group(1)}"
            log.info(f"  [{retailer}] using CamelCamelCamel (ASIN {m.group(1)}) to avoid Amazon block")

    # Random jitter 0-2s: staggers concurrent requests so the corporate proxy
    # doesn't receive all connections simultaneously and fail with ERR_PROXY_CONNECTION_FAILED
    await asyncio.sleep(random.uniform(0, 2.0))

    async with semaphore:
        page = None
        try:
            hostname = urlparse(actual_url).hostname or ""
            # Costco price loads via a separate React render; needs more time
            if "costco.com" in hostname:
                wait_ms = 11000
            # Target/Best Buy need time for React hydration
            elif "target.com" in hostname or "bestbuy.com" in hostname:
                wait_ms = 8000
            else:
                wait_ms = 5000

            page = await context.new_page()
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
                window.Notification = {permission: 'default'};
            """)
            # Block images/fonts for speed
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3}",
                lambda route: route.abort(),
            )

            for attempt in range(2):
                try:
                    await page.goto(actual_url, wait_until="domcontentloaded", timeout=45_000)

                    # For Costco: wait for the React price component to render
                    # (verified selector: data-testid="single-price-content")
                    if "costco.com" in hostname:
                        try:
                            await page.wait_for_selector(
                                '[data-testid="single-price-content"], [data-testid="price"]',
                                timeout=wait_ms,
                            )
                        except Exception:
                            pass  # Fall through; _extract_price will try all selectors
                    else:
                        await page.wait_for_timeout(wait_ms)

                    price = await _extract_price(page, actual_url)
                    if price:
                        result["price"] = round(price, 2)
                        log.info(f"  [{retailer}] ${price:.2f}")
                        return result

                    if attempt == 0:
                        await page.wait_for_timeout(4000)

                except PlaywrightTimeout:
                    if attempt == 0:
                        continue
                    result["error"] = "Timeout"
                    return result

            result["error"] = "Price not found"
            log.warning(f"  [{retailer}] could not extract price")

        except Exception as exc:
            err = str(exc)[:120]
            result["error"] = err
            log.warning(f"  [{retailer}] {err}")
        finally:
            if page:
                await page.close()

    return result


def _copy_chrome_profile() -> str:
    """
    Copy the Chrome profile to a temp dir so Playwright can use it
    even while Chrome might be running (avoids lock file conflicts).
    Only copies the essential files (Cookies, Local State, Preferences).
    """
    src = Path(CHROME_PROFILE)
    tmp = Path(tempfile.mkdtemp(prefix="wmt_price_"))
    default_src = src / "Default"
    default_dst = tmp / "Default"
    default_dst.mkdir(parents=True, exist_ok=True)

    # Copy essential files for session/cookies
    for fname in ["Cookies", "Preferences", "Local State"]:
        f = default_src / fname
        if f.exists():
            try:
                shutil.copy2(f, default_dst / fname)
            except Exception:
                pass

    # Copy Local State (needed for Chrome to launch)
    ls = src / "Local State"
    if ls.exists():
        try:
            shutil.copy2(ls, tmp / "Local State")
        except Exception:
            pass

    return str(tmp)


async def scrape_all_prices(competitors: list[dict]) -> list[dict]:
    """Scrape all competitors using real Chrome with user profile."""
    # 2 concurrent max: 3 simultaneous HTTPS connections overwhelm the Walmart
    # corporate proxy and cause ERR_PROXY_CONNECTION_FAILED for the first batch
    semaphore = asyncio.Semaphore(2)
    profile_dir = None

    try:
        profile_dir = _copy_chrome_profile()
        log.info(f"Using Chrome profile copy at: {profile_dir}")
    except Exception as e:
        log.warning(f"Could not copy Chrome profile: {e} — using fresh context")
        profile_dir = None

    base_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--ignore-certificate-errors",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1920,1080",
        "--window-position=-10000,0",   # off-screen: invisible but not headless
        "--disable-extensions",
        "--disable-infobars",
        "--disable-http2",              # fixes ERR_HTTP2_PROTOCOL_ERROR on some sites
    ]
    ctx_opts = dict(
        executable_path=CHROME_PATH,
        headless=False,   # non-headless = real Chrome fingerprint → bypasses bot detection
        args=base_args,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        ignore_https_errors=True,
        # No custom user_agent — use Chrome's own real UA (fake versions trigger Amazon)
    )

    async with async_playwright() as p:
        browser = None
        if profile_dir:
            # launch_persistent_context requires user_data_dir as first positional arg
            context = await p.chromium.launch_persistent_context(profile_dir, **ctx_opts)
        else:
            # Fallback: fresh browser without profile
            browser = await p.chromium.launch(
                executable_path=CHROME_PATH,
                headless=False,
                args=base_args,
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                ignore_https_errors=True,
            )

        # Warm-up: navigate a blank page then wait 3s.
        # Chrome needs time to load proxy settings from the user profile —
        # without this the first 2-3 real pages fail with ERR_PROXY_CONNECTION_FAILED.
        try:
            warmup = await context.new_page()
            await warmup.goto("about:blank", timeout=5000)
            await warmup.close()
            await asyncio.sleep(5)  # 5s: Chrome needs time to apply proxy settings
        except Exception:
            pass

        try:
            tasks = [_scrape_one(context, c, semaphore) for c in competitors]
            results = await asyncio.gather(*tasks)
        finally:
            await context.close()
            if browser:
                await browser.close()

    # Cleanup temp profile
    if profile_dir:
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass

    return list(results)
