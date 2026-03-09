"""
Database operations for the used cars monitor.
Uses SQLite to store car listings and price history.
"""

import sqlite3
import os
from datetime import datetime, timezone
from contextlib import contextmanager


def get_db_path():
    data_dir = os.getenv("DATA_DIR", "./data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "cars.db")


@contextmanager
def get_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cars (
                id          TEXT PRIMARY KEY,
                url         TEXT NOT NULL,
                brand       TEXT,
                model       TEXT,
                specs       TEXT,
                fuel        TEXT,
                transmission TEXT,
                year        INTEGER,
                km          INTEGER,
                location    TEXT,
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL,
                active      INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                car_id      TEXT NOT NULL,
                price       INTEGER NOT NULL,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY (car_id) REFERENCES cars(id)
            );

            CREATE INDEX IF NOT EXISTS idx_price_car_id ON price_history(car_id);
            CREATE INDEX IF NOT EXISTS idx_cars_active ON cars(active);
        """)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def upsert_cars(scraped_cars: list[dict]) -> dict:
    """
    Update the database with freshly scraped cars.
    Returns a summary dict with counts of new/updated/disappeared cars.
    """
    init_db()
    ts = now_iso()

    with get_connection() as conn:
        # Get all currently active car IDs
        active_ids = {
            row["id"]
            for row in conn.execute("SELECT id FROM cars WHERE active=1")
        }
        scraped_ids = {car["id"] for car in scraped_cars}

        summary = {"new": 0, "price_changed": 0, "disappeared": 0, "unchanged": 0}

        # Process each scraped car
        for car in scraped_cars:
            cid = car["id"]
            existing = conn.execute(
                "SELECT * FROM cars WHERE id=?", (cid,)
            ).fetchone()

            if existing is None:
                # New listing
                conn.execute(
                    """INSERT INTO cars
                       (id, url, brand, model, specs, fuel, transmission,
                        year, km, location, first_seen, last_seen, active)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (
                        cid,
                        car.get("url", ""),
                        car.get("brand", ""),
                        car.get("model", ""),
                        car.get("specs", ""),
                        car.get("fuel", ""),
                        car.get("transmission", ""),
                        car.get("year"),
                        car.get("km"),
                        car.get("location", ""),
                        ts,
                        ts,
                    ),
                )
                if car.get("price") is not None:
                    conn.execute(
                        "INSERT INTO price_history (car_id, price, recorded_at) VALUES (?,?,?)",
                        (cid, car["price"], ts),
                    )
                summary["new"] += 1

            else:
                # Existing car — update last_seen, re-activate if it was gone, track price changes
                conn.execute(
                    """UPDATE cars SET last_seen=?, active=1,
                       km=COALESCE(?,km)
                       WHERE id=?""",
                    (ts, car.get("km"), cid),
                )

                if car.get("price") is not None:
                    last_price = conn.execute(
                        """SELECT price FROM price_history
                           WHERE car_id=? ORDER BY recorded_at DESC LIMIT 1""",
                        (cid,),
                    ).fetchone()

                    if last_price is None or last_price["price"] != car["price"]:
                        conn.execute(
                            "INSERT INTO price_history (car_id, price, recorded_at) VALUES (?,?,?)",
                            (cid, car["price"], ts),
                        )
                        summary["price_changed"] += 1
                    else:
                        summary["unchanged"] += 1

        # Mark cars no longer in the listing as inactive
        gone_ids = active_ids - scraped_ids
        for gid in gone_ids:
            conn.execute(
                "UPDATE cars SET active=0, last_seen=? WHERE id=?", (ts, gid)
            )
            summary["disappeared"] += 1

    return summary


def get_all_cars() -> list[dict]:
    """Return all cars with their full price history."""
    init_db()
    with get_connection() as conn:
        cars = conn.execute(
            "SELECT * FROM cars ORDER BY active DESC, first_seen DESC"
        ).fetchall()

        result = []
        for car in cars:
            car_dict = dict(car)
            history = conn.execute(
                """SELECT price, recorded_at FROM price_history
                   WHERE car_id=? ORDER BY recorded_at ASC""",
                (car["id"],),
            ).fetchall()
            car_dict["price_history"] = [dict(h) for h in history]
            car_dict["current_price"] = (
                history[-1]["price"] if history else None
            )
            result.append(car_dict)

    return result


def get_stats() -> dict:
    init_db()
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM cars").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM cars WHERE active=1").fetchone()[0]
        inactive = total - active

        # Cars seen today
        today = datetime.now(timezone.utc).date().isoformat()
        new_today = conn.execute(
            "SELECT COUNT(*) FROM cars WHERE first_seen >= ?", (today,)
        ).fetchone()[0]
        gone_today = conn.execute(
            "SELECT COUNT(*) FROM cars WHERE active=0 AND last_seen >= ?", (today,)
        ).fetchone()[0]

    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "new_today": new_today,
        "gone_today": gone_today,
    }
