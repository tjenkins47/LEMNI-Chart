import csv
import os
import sqlite3
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template, request

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except Exception:
    BackgroundScheduler = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "lemni_prices.sqlite")
SEED_CSV_PATH = os.path.join(APP_DIR, "lemni_price_seed.csv")

NETWORK = "polygon_pos"
POOL_ADDRESS = "0x28289c9d971edb8a1d50d3891bb5c91d0fa3992e"
POOL_API = f"https://api.geckoterminal.com/api/v2/networks/{NETWORK}/pools/{POOL_ADDRESS}"
FETCH_INTERVAL_MINUTES = int(os.environ.get("FETCH_INTERVAL_MINUTES", "15"))
LOCAL_PORT = int(os.environ.get("PORT", "5005"))
LAST_FETCH = {"status": "not_started", "message": "", "timestamp_utc": None, "price": None}

app = Flask(__name__)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS price_points (
                timestamp_utc TEXT PRIMARY KEY,
                price REAL NOT NULL,
                source TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fetch_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_utc TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                price REAL
            )
            """
        )
        conn.commit()


def db_has_prices():
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM price_points").fetchone()
        return row["n"] > 0


def parse_seed_date(value):
    # Google Sheets export is expected to be M/D/YYYY or MM/DD/YYYY.
    dt = datetime.strptime(value.strip(), "%m/%d/%Y")
    return dt.replace(tzinfo=timezone.utc).isoformat()


def import_seed_csv(force=False):
    if not os.path.exists(SEED_CSV_PATH):
        return {"imported": 0, "message": "No seed CSV found."}

    if db_has_prices() and not force:
        return {"imported": 0, "message": "Database already has price data; seed import skipped."}

    imported = 0
    now = datetime.now(timezone.utc).isoformat()

    with open(SEED_CSV_PATH, newline="", encoding="utf-8-sig") as f, get_db() as conn:
        reader = csv.DictReader(f)
        for row in reader:
            date_value = (row.get("Date") or "").strip()
            price_value = (row.get("Price") or "").strip()
            if not date_value or not price_value:
                continue
            ts = parse_seed_date(date_value)
            price = float(price_value.replace("$", "").replace(",", ""))
            conn.execute(
                """
                INSERT OR IGNORE INTO price_points
                (timestamp_utc, price, source, created_at_utc)
                VALUES (?, ?, ?, ?)
                """,
                (ts, price, "seed_csv", now),
            )
            imported += 1
        conn.commit()

    return {"imported": imported, "message": "Seed CSV import complete."}


def save_price(timestamp_utc, price, source):
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO price_points
            (timestamp_utc, price, source, created_at_utc)
            VALUES (?, ?, ?, ?)
            """,
            (
                timestamp_utc,
                float(price),
                source,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def log_fetch(status, message="", price=None):
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    LAST_FETCH.update({
        "status": status,
        "message": message,
        "timestamp_utc": ts,
        "price": price,
    })
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO fetch_log (timestamp_utc, status, message, price)
            VALUES (?, ?, ?, ?)
            """,
            (ts, status, message, price),
        )
        conn.commit()


def fetch_current_price():
    try:
        response = requests.get(POOL_API, timeout=20)
        response.raise_for_status()
        data = response.json()
        attrs = data.get("data", {}).get("attributes", {})
        price = float(attrs.get("base_token_price_usd") or 0)
        if price <= 0:
            raise ValueError("GeckoTerminal returned an invalid price.")

        # Store at minute precision to prevent noisy duplicate rows every few seconds.
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
        save_price(now, price, "geckoterminal_pool")
        log_fetch("ok", "Saved latest GeckoTerminal price.", price)
        print(f"Background fetch OK: {now} ${price:.6f}")
        return {"timestamp_utc": now, "price": price}
    except Exception as e:
        log_fetch("error", str(e), None)
        print(f"Background fetch ERROR: {e}")
        raise

def fetch_pool_data():
    url = f"https://api.geckoterminal.com/api/v2/networks/{NETWORK}/pools/{POOL_ADDRESS}"
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    payload = response.json()
    attrs = payload.get("data", {}).get("attributes", {})

    return {
        "price_change_24h": float(attrs.get("price_change_percentage", {}).get("h24") or 0),
        "volume_24h": float(attrs.get("volume_usd", {}).get("h24") or 0),
        "liquidity": float(attrs.get("reserve_in_usd") or 0),
        "market_cap": float(attrs.get("market_cap_usd") or attrs.get("fdv_usd") or 0)
    }

def range_start_sql(range_key, end_timestamp):
    end_dt = datetime.fromisoformat(end_timestamp.replace("Z", "+00:00"))
    year_start = datetime(end_dt.year, 1, 1, tzinfo=timezone.utc).isoformat()

    mapping = {
        "1D": "datetime(?, '-1 day')",
        "7D": "datetime(?, '-7 days')",
        "1M": "datetime(?, '-1 month')",
        "6M": "datetime(?, '-6 months')",
        "1Y": "datetime(?, '-1 year')",
        "5Y": "datetime(?, '-5 years')",
    }

    if range_key == "YTD":
        return year_start
    return mapping.get(range_key, "datetime(?, '-1 month')")


def get_history(range_key):
    range_key = (range_key or "1M").upper()

    with get_db() as conn:
        end_row = conn.execute("SELECT MAX(timestamp_utc) AS max_ts FROM price_points").fetchone()
        end_ts = end_row["max_ts"]
        if not end_ts:
            return []

        if range_key == "YTD":
            start_ts = range_start_sql(range_key, end_ts)
            rows = conn.execute(
                """
                SELECT timestamp_utc, price, source
                FROM price_points
                WHERE timestamp_utc >= ?
                ORDER BY timestamp_utc ASC
                """,
                (start_ts,),
            ).fetchall()
        else:
            sql_start = range_start_sql(range_key, end_ts)
            rows = conn.execute(
                f"""
                SELECT timestamp_utc, price, source
                FROM price_points
                WHERE timestamp_utc >= {sql_start}
                ORDER BY timestamp_utc ASC
                """,
                (end_ts,),
            ).fetchall()

    return [dict(row) for row in rows]


@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/market")
def api_market():
    try:
        data = fetch_pool_data()
        return jsonify(data)
    except Exception as e:
        return jsonify({
            "error": str(e),
            "price_change_24h": None,
            "volume_24h": None,
            "liquidity": None,
            "market_cap": None
        }), 500

@app.get("/api/history")
def api_history():
    range_key = request.args.get("range", "1M")
    points = get_history(range_key)
    latest = points[-1] if points else None
    return jsonify({"range": range_key, "points": points, "latest": latest})


@app.post("/api/refresh")
def api_refresh():
    try:
        latest = fetch_current_price()
        return jsonify({"status": "ok", "latest": latest})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/status")
def api_status():
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count, MIN(timestamp_utc) AS first_ts, MAX(timestamp_utc) AS last_ts
            FROM price_points
            """
        ).fetchone()
        log_row = conn.execute(
            """
            SELECT timestamp_utc, status, message, price
            FROM fetch_log
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    payload = dict(row)
    payload["fetch_interval_minutes"] = FETCH_INTERVAL_MINUTES
    payload["last_fetch"] = dict(log_row) if log_row else LAST_FETCH
    return jsonify(payload)


def start_scheduler():
    if BackgroundScheduler is None:
        print("APScheduler is not installed; background fetcher is disabled.")
        return
    if os.environ.get("DISABLE_SCHEDULER") == "1":
        print("Background fetcher disabled by DISABLE_SCHEDULER=1.")
        return

    # Flask debug mode uses a reloader that imports the app twice. This guard prevents
    # two duplicate background schedulers from running locally.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        fetch_current_price,
        "interval",
        minutes=FETCH_INTERVAL_MINUTES,
        id="fetch_lemni_price",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    print(f"Background fetcher started: every {FETCH_INTERVAL_MINUTES} minutes.")


init_db()
import_seed_csv(force=False)
try:
    fetch_current_price()
except Exception as e:
    print(f"Startup GeckoTerminal fetch skipped/failed: {e}")
start_scheduler()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=LOCAL_PORT, debug=True)
