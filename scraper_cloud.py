"""
scraper_cloud.py - Linux/cloud compatible price scraper.
Uses Playwright's bundled Chromium (no Windows Chrome needed).
Runs from Render.com — outside Walmart's corporate network,
so Best Buy, Target, Amazon, and Costco are accessible.
"""

import asyncio
import re
import logging
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger(__name__)

PRICE_REGEX = re.compile(r"\$?([\d,]+\.\d{2})")

SITE_SELECTORS: dict[str, list[str]] = {
    "bhphotovideo.com": [
        '[data-selenium="pricingPrice"]',
        '[class*="price_salePrice"]',
        '[class*="price_Price"]',
    ],
    "amazon.com": [
        '.a-price.apexPriceToPay .a-offscreen',
        '#apex_desktop_newAccordionRow .a-price .a-offscreen',
        '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
        '[data-feature-name="apex_desktop"] .a-price .a-offscreen',
        '.a-price[data-a-size="xl"] .a-offscreen',
        '.a-price[data-a-size="b"] .a-offscreen',
        '.a-price .a-offscreen',
        '#price_inside_buybox',
        '#priceblock_ourprice',
        '.priceToPay .a-offscreen',
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
        '.your-price .value',
        '[automation-id="product-price"]',
        '[itemprop="price"]',
        'div[class*="price"] span',
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
        r'"currentRetail"\s*:\s*([\d.]+)',
        r'"currentPrice"\s*:\s*([\d.]+)',
        r'"offerPrice"\s*:\s*([\d.]+)',
        r'"salePrice"\s*:\s*([\d.]+)',
        r'"finalPrice"\s*:\s*([\d.]+)',
        r'"lowestPrice"\s*:\s*([\d.]+)',
        r'"listPrice"\s*:\s*([\d.]+)',
        r'"regularPrice"\s*:\s*([\d.]+)',
        r'"customerPrice"\s*:\s*([\d.]+)',
        r'"price"\s*:\s*"?([\d.]+)"?',
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

    # JSON-LD
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

    # Next.js __NEXT_DATA__
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

    # Meta price tags
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

    # Raw page source
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

    async with semaphore:
        page = None
        try:
            hostname = urlparse(url).hostname or ""
            if "target.com" in hostname or "bestbuy.com" in hostname:
                wait_ms = 8000
            elif "costco.com" in hostname or "amazon.com" in hostname:
                wait_ms = 7000
            else:
                wait_ms = 5000

            page = await context.new_page()
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            """)
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3}",
                lambda route: route.abort(),
            )
            await page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })

            for attempt in range(2):
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    await page.wait_for_timeout(wait_ms)

                    price = await _extract_price(page, url)
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


async def scrape_all_prices(competitors: list[dict]) -> list[dict]:
    """Scrape all competitors using Playwright's Chromium (cloud/Linux compatible)."""
    semaphore = asyncio.Semaphore(1)  # limit concurrency on cloud (512MB RAM)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--no-zygote",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        try:
            tasks = [_scrape_one(context, c, semaphore) for c in competitors]
            results = await asyncio.gather(*tasks)
        finally:
            await context.close()
            await browser.close()

    return list(results)
