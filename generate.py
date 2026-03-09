"""
Static HTML page generator.
Reads all car data from the database and renders a Jinja2 template.
"""

import os
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

import db
from ai_rating import rate_cars_if_needed

logger = logging.getLogger(__name__)


def _format_price(price: int | None) -> str:
    if price is None:
        return "—"
    return f"{price:,.0f} €".replace(",", ".")


def _format_km(km: int | None) -> str:
    if km is None:
        return "—"
    return f"{km:,.0f} km".replace(",", ".")


def _format_dt(iso_str: str | None) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso_str


def _price_delta(history: list[dict]) -> str:
    """Return a human-readable price change summary."""
    if len(history) < 2:
        return ""
    first = history[0]["price"]
    last = history[-1]["price"]
    delta = last - first
    if delta == 0:
        return ""
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:,.0f} €".replace(",", ".")


def generate(output_dir: str | None = None, rerate: bool = False):
    output_dir = output_dir or os.getenv("OUTPUT_DIR", "./output")
    os.makedirs(output_dir, exist_ok=True)

    cars = db.get_all_cars()
    stats = db.get_stats()

    # AI rating (skipped if OPENAI_API_KEY is not set)
    rate_cars_if_needed(cars, force=rerate)

    # Base URL for building absolute links
    target_url = os.getenv("TARGET_URL", "")
    parsed = urlparse(target_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""

    # Enrich cars with display helpers
    for car in cars:
        car["display_price"] = _format_price(car.get("current_price"))
        car["display_km"] = _format_km(car.get("km"))
        car["display_first_seen"] = _format_dt(car.get("first_seen"))
        car["display_last_seen"] = _format_dt(car.get("last_seen"))
        car["price_delta"] = _price_delta(car.get("price_history", []))
        # Make car URL absolute
        url = car.get("url", "")
        if url and not url.startswith("http") and base_url:
            car["url"] = base_url + ("" if url.startswith("/") else "/") + url

        car["title"] = " ".join(
            filter(None, [car.get("brand"), car.get("model")])
        ) or "Vehículo sin nombre"

        # Format each price history entry for display
        for entry in car.get("price_history", []):
            entry["display_price"] = _format_price(entry["price"])
            entry["display_date"] = _format_dt(entry["recorded_at"])

    generated_at = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("index.html")

    html = template.render(
        cars=cars,
        stats=stats,
        generated_at=generated_at,
    )

    output_path = os.path.join(output_dir, "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"Page generated: {output_path} ({len(cars)} cars)")
    return output_path
