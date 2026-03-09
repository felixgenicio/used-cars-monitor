"""
Scraper for used car listings.
Uses Playwright to handle JavaScript-rendered pages.
Intercepts API calls to capture structured data; falls back to DOM parsing.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from urllib.parse import unquote

from playwright.async_api import async_playwright, Page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_price(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    cleaned = re.sub(r"[^\d]", "", str(value))
    return int(cleaned) if cleaned else None


def _parse_km(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    cleaned = re.sub(r"[^\d]", "", str(value))
    return int(cleaned) if cleaned else None


def _extract_uuid(text: str) -> str | None:
    match = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        text,
        re.IGNORECASE,
    )
    return match.group(0) if match else None


# ---------------------------------------------------------------------------
# URL slug parser — primary data source
# ---------------------------------------------------------------------------
# Slug pattern: brand-model-specs-fuel-de-YEAR-en-CITY-de-segunda-mano-UUID

_FUEL_MAP = {
    "electrico-hibrido": "Híbrido enchufable",
    "gasolina":          "Gasolina",
    "diesel":            "Diésel",
    "electrico":         "Eléctrico",
    "hibrido":           "Híbrido",
    "gas":               "Gas natural",
    "glp":               "GLP",
}

# Known multi-word brands (slug uses hyphens)
_MULTI_WORD_BRANDS = {
    "mercedes-benz", "alfa-romeo", "aston-martin", "land-rover",
    "rolls-royce", "mg-motor", "ds-automobiles",
}


def _parse_slug(slug: str) -> dict:
    """
    Extract brand, model, specs, fuel, year and location from a URL slug.
    Example: /omoda-5-16-t-gdi-gasolina-de-2024-en-zaragoza-de-segunda-mano-UUID
    """
    path = unquote(slug.lstrip("/"))

    # Remove UUID
    path = re.sub(
        r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        "",
        path,
        flags=re.IGNORECASE,
    )

    # Remove -de-segunda-mano
    path = re.sub(r"-de-segunda-mano$", "", path)

    # Extract year and location: -de-YEAR-en-CITY
    year = None
    location = ""
    m = re.search(r"-de-(\d{4})-en-(.+)$", path)
    if m:
        year = int(m.group(1))
        location = m.group(2).replace("-", " ").title()
        path = path[: m.start()]

    # Extract fuel (longest match first to handle "electrico-hibrido")
    fuel = ""
    for slug_fuel in sorted(_FUEL_MAP, key=len, reverse=True):
        if path.endswith("-" + slug_fuel):
            fuel = _FUEL_MAP[slug_fuel]
            path = path[: -(len(slug_fuel) + 1)]
            break

    # Detect multi-word brand
    brand_raw = ""
    model_raw = ""
    specs_raw = ""
    for mb in _MULTI_WORD_BRANDS:
        if path.startswith(mb + "-"):
            brand_raw = mb
            rest = path[len(mb) + 1:]
            parts = rest.split("-", 1)
            model_raw = parts[0]
            specs_raw = parts[1] if len(parts) > 1 else ""
            break
    else:
        parts = path.split("-", 2)
        brand_raw = parts[0]
        model_raw = parts[1] if len(parts) > 1 else ""
        specs_raw = parts[2] if len(parts) > 2 else ""

    def title_case(s: str) -> str:
        return s.replace("-", " ").upper() if len(s) <= 4 else s.replace("-", " ").title()

    return {
        "brand": brand_raw.replace("-", " ").upper(),
        "model": title_case(model_raw),
        "specs": specs_raw.replace("-", " "),
        "fuel": fuel,
        "year": year,
        "location": location,
    }


# ---------------------------------------------------------------------------
# API response helpers
# ---------------------------------------------------------------------------

def _looks_like_vehicle_list(data) -> bool:
    if not isinstance(data, list) or len(data) == 0:
        return False
    sample = data[0]
    if not isinstance(sample, dict):
        return False
    keys_lower = {k.lower() for k in sample.keys()}
    vehicle_keys = {"price", "km", "year", "brand", "model", "fuel", "slug", "id", "uuid"}
    return len(keys_lower & vehicle_keys) >= 2


def _find_vehicle_list(data) -> list | None:
    if _looks_like_vehicle_list(data):
        return data
    if isinstance(data, dict):
        for value in data.values():
            result = _find_vehicle_list(value)
            if result:
                return result
    if isinstance(data, list):
        for item in data:
            result = _find_vehicle_list(item)
            if result:
                return result
    return None


def _normalize_from_api(v: dict) -> dict | None:
    def get(*keys):
        for k in keys:
            val = v.get(k)
            if val is not None:
                return val
        return None

    url_slug = get("slug", "url", "permalink", "link", "path") or ""
    car_id = (
        get("id", "uuid", "vehicleId", "vehicle_id")
        or _extract_uuid(url_slug)
        or _extract_uuid(json.dumps(v))
    )
    if not car_id:
        return None

    slug_data = _parse_slug(url_slug) if url_slug else {}
    raw_price = get("price", "precio", "cashPrice", "cash_price", "salePrice")
    raw_km = get("km", "kilometers", "mileage", "kilometros", "odometer")

    return {
        "id": str(car_id),
        "url": url_slug,
        "brand": get("brand", "marca", "make") or slug_data.get("brand", ""),
        "model": get("model", "modelo") or slug_data.get("model", ""),
        "specs": get("version", "specs", "trim", "engine") or slug_data.get("specs", ""),
        "fuel": get("fuel", "combustible", "fuelType") or slug_data.get("fuel", ""),
        "transmission": get("transmission", "transmision", "gearbox") or "",
        "year": get("year", "año", "registrationYear") or slug_data.get("year"),
        "km": _parse_km(raw_km),
        "location": get("location", "ciudad", "city") or slug_data.get("location", ""),
        "price": _parse_price(raw_price),
    }


# ---------------------------------------------------------------------------
# DOM parser (fallback)
# ---------------------------------------------------------------------------

async def _parse_from_dom(page: Page, base_url: str) -> list[dict]:
    """
    Extract vehicle data from the rendered DOM.
    Parses the URL slug for most fields; extracts price/km from nearby DOM text.
    """
    logger.info("Falling back to DOM parsing")

    items = await page.evaluate("""
        () => {
            const uuidRe = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
            const results = [];
            const seen = new Set();

            document.querySelectorAll('a[href]').forEach(a => {
                if (!uuidRe.test(a.href)) return;
                const uuid = a.href.match(uuidRe)[0];
                if (seen.has(uuid)) return;
                seen.add(uuid);

                // Walk up to find a container that contains price (€) and km
                let container = a;
                for (let i = 0; i < 15; i++) {
                    if (!container.parentElement) break;
                    const parent = container.parentElement;
                    const t = parent.innerText || '';
                    if ((t.includes('€') || t.includes('\u20ac')) &&
                        (t.includes(' km') || t.includes('\u00a0km'))) {
                        container = parent;
                        break;
                    }
                    container = parent;
                }

                try {
                    const url = new URL(a.href);
                    results.push({
                        href: a.href,
                        slug: url.pathname,
                        text: container.innerText || ''
                    });
                } catch(e) {}
            });
            return results;
        }
    """)

    cars = []
    seen_ids = set()

    # Patterns for price and km in DOM text
    # Prices look like "24.900\u00a0€" or "24900 €"
    price_re = re.compile(r"(\d[\d.\u00a0 ]{1,8})\s*(?:\u20ac|€)", re.UNICODE)
    km_re = re.compile(r"(\d[\d.\u00a0 ]{1,8})\s*km", re.IGNORECASE | re.UNICODE)
    transmission_re = re.compile(r"\b(autom[aá]tico|manual)\b", re.IGNORECASE)
    location_re = re.compile(r"\b(zaragoza|madrid|barcelona|valencia|sevilla|bilbao|m[aá]laga|murcia)\b", re.IGNORECASE)

    for item in items:
        href = item.get("href", "")
        car_id = _extract_uuid(href)
        if not car_id or car_id in seen_ids:
            continue
        seen_ids.add(car_id)

        slug = item.get("slug", "")
        text = item.get("text", "")

        # Primary data from URL slug
        slug_data = _parse_slug(slug)

        # Price: find all candidate prices, pick the largest (main cash price)
        raw_prices = price_re.findall(text)
        prices = []
        for p in raw_prices:
            cleaned = re.sub(r"[^\d]", "", p)
            if cleaned and 1000 <= int(cleaned) <= 500_000:
                prices.append(int(cleaned))
        price = max(prices) if prices else None

        # KM: first km value
        km_match = km_re.search(text)
        km = int(re.sub(r"[^\d]", "", km_match.group(1))) if km_match else None

        # Transmission
        tx_match = transmission_re.search(text)
        transmission = tx_match.group(1).capitalize() if tx_match else ""

        # Location override from DOM if slug didn't provide it
        location = slug_data.get("location", "")
        if not location:
            loc_match = location_re.search(text)
            location = loc_match.group(1).title() if loc_match else ""

        # Build URL: use full href or just the path
        url_path = slug if slug else re.sub(r"^https?://[^/]+", "", href)

        cars.append({
            "id": car_id,
            "url": url_path,
            "brand": slug_data.get("brand", ""),
            "model": slug_data.get("model", ""),
            "specs": slug_data.get("specs", ""),
            "fuel": slug_data.get("fuel", "") or _extract_fuel_from_text(text),
            "transmission": transmission,
            "year": slug_data.get("year"),
            "km": km,
            "location": location,
            "price": price,
        })

    logger.info(f"DOM parser found {len(cars)} vehicles")
    return cars


def _extract_fuel_from_text(text: str) -> str:
    text_lower = text.lower()
    if "eléctrico" in text_lower or "electrico" in text_lower:
        return "Eléctrico"
    if "híbrido enchufable" in text_lower or "plug-in" in text_lower:
        return "Híbrido enchufable"
    if "híbrido" in text_lower or "hibrido" in text_lower:
        return "Híbrido"
    if "diésel" in text_lower or "diesel" in text_lower:
        return "Diésel"
    if "gasolina" in text_lower:
        return "Gasolina"
    return ""


# ---------------------------------------------------------------------------
# Main scrape function
# ---------------------------------------------------------------------------

async def scrape(target_url: str, debug_dir: str | None = None) -> list[dict]:
    """
    Scrape vehicles from target_url.
    If debug_dir is set, dumps all captured API responses there for inspection.
    """
    captured_responses: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        async def on_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct or response.status != 200:
                    return
                body = await response.json()
                captured_responses.append({"url": response.url, "data": body})
            except Exception:
                pass

        page.on("response", on_response)

        logger.info(f"Navigating to {target_url}")
        try:
            await page.goto(target_url, wait_until="networkidle", timeout=90_000)
        except Exception as exc:
            logger.warning(f"Page load warning (continuing): {exc}")

        # Extra wait for JS to finish initializing after networkidle
        await asyncio.sleep(3)

        # Scroll in viewport-sized steps; re-check page height each time
        # because lazy-loaded content can make the page grow dynamically.
        logger.info("Scrolling page to trigger lazy loading...")
        viewport_h = 900
        position = 0
        for _ in range(60):  # up to 60 steps (~54 000 px max)
            position += viewport_h
            await page.evaluate(f"window.scrollTo(0, {position})")
            await asyncio.sleep(1.5)
            page_height = await page.evaluate("document.body.scrollHeight")
            if position >= page_height:
                break

        # Final wait for any remaining content to render
        await asyncio.sleep(3)

        # Save debug dump if requested
        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_path = os.path.join(debug_dir, f"api_responses_{ts}.json")
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(captured_responses, f, ensure_ascii=False, indent=2)
            logger.info(f"Debug API responses saved to {debug_path}")

        # Try API interception first
        cars = []
        for resp in captured_responses:
            vehicle_list = _find_vehicle_list(resp["data"])
            if vehicle_list:
                logger.info(
                    f"Found vehicle list ({len(vehicle_list)} items) via API: {resp['url']}"
                )
                for v in vehicle_list:
                    car = _normalize_from_api(v)
                    if car:
                        cars.append(car)
                if cars:
                    break

        # Fall back to DOM parsing
        if not cars:
            cars = await _parse_from_dom(page, target_url)

        await browser.close()

    # Deduplicate by id
    seen = set()
    unique_cars = []
    for car in cars:
        if car["id"] not in seen:
            seen.add(car["id"])
            unique_cars.append(car)

    logger.info(f"Scrape complete: {len(unique_cars)} unique vehicles found")
    return unique_cars


def run_scrape(target_url: str, debug: bool = False) -> list[dict]:
    debug_dir = os.getenv("LOG_DIR", "./logs") if debug else None
    return asyncio.run(scrape(target_url, debug_dir=debug_dir))
