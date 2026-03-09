"""
AI-powered price rating for used car listings.
Calls OpenAI to assess whether a car's price is good, fair, or expensive.
Results are cached in the DB keyed by (car_id, price) to avoid redundant calls.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)


def rate_car(car: dict) -> tuple[str | None, str | None]:
    """
    Ask OpenAI to rate the car's price.
    Returns (rating, justification) where rating is 'green', 'yellow', or 'red',
    or (None, None) if the API key is missing or the call fails.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping AI rating")
        return None, None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except ImportError:
        logger.error("openai package not installed — run: pip install openai")
        return None, None

    price = car.get("current_price")
    if price is None:
        return None, None

    prompt = (
        "Eres un experto en el mercado de coches de segunda mano en España. "
        "Analiza el siguiente anuncio y valora si el precio es bueno, normal o caro para el comprador, "
        "comparando con el mercado actual. Compara con precios reales actuales.\n\n"
        f"Marca/Modelo: {car.get('brand', '')} {car.get('model', '')}\n"
        f"Año: {car.get('year', 'desconocido')}\n"
        f"Kilómetros: {car.get('km', 'desconocido')}\n"
        f"Precio: {price} €\n"
        f"Combustible: {car.get('fuel', 'desconocido')}\n"
        f"Transmisión: {car.get('transmission', 'desconocida')}\n"
        f"Especificaciones: {car.get('specs', '')}\n\n"
        "Responde ÚNICAMENTE con un JSON con este formato exacto:\n"
        '{"rating": "green"|"yellow"|"red", "justification": "texto breve en español (máximo 2 frases)"}\n\n'
        "- green: precio muy bueno, claramente por debajo del mercado\n"
        "- yellow: precio normal, acorde al mercado\n"
        "- red: precio caro, por encima del mercado"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-search-preview",
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content
        # Extract JSON block from the response (model may wrap it in markdown)
        import re
        json_match = re.search(r'\{[^{}]+\}', content, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON found in response: {content!r}")
        data = json.loads(json_match.group())
        rating = data.get("rating", "yellow")
        justification = data.get("justification", "")

        if rating not in ("green", "yellow", "red"):
            rating = "yellow"

        return rating, justification

    except Exception as exc:
        logger.error(f"OpenAI API error for car {car.get('id')}: {exc}")
        return None, None


def rate_cars_if_needed(cars: list[dict], force: bool = False) -> None:
    """
    For each car that lacks a rating or whose price has changed since the last rating,
    call rate_car() and persist the result to the DB.
    Pass force=True to re-rate all cars regardless of cached values.
    Modifies car dicts in-place so the template sees updated values.
    """
    import db

    for car in cars:
        current_price = car.get("current_price")
        rated_price = car.get("ai_rated_price")

        needs_rating = force or (
            car.get("ai_rating") is None
            or (current_price is not None and current_price != rated_price)
        )

        if not needs_rating:
            continue

        logger.info(
            f"Rating car {car['id']} ({car.get('brand')} {car.get('model')}, {current_price} €)…"
        )
        rating, justification = rate_car(car)

        if rating is None:
            # API key missing or call failed — stop trying for remaining cars
            break

        db.save_car_rating(car["id"], rating, justification, current_price)

        # Update in-place so the template renders fresh values immediately
        car["ai_rating"] = rating
        car["ai_justification"] = justification
        car["ai_rated_price"] = current_price
