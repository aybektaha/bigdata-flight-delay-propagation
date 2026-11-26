import os
import time
import json
import gzip
import base64
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
import requests
from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

OPENSKY_USER = os.environ["OPENSKY_USER"]
OPENSKY_PASS = os.environ["OPENSKY_PASS"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

AUTH = (OPENSKY_USER, OPENSKY_PASS)
BASE_URL = "https://opensky-network.org/api"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BBOX_PARAMS = {
    "lamin": 39.70,
    "lamax": 42.90,
    "lomin": 26.80,
    "lomax": 30.80,
}

POLL_INTERVAL = 22.0
ARRIVAL_INTERVAL = 3600.0
FALLBACK_FILE = "unsent_buffer.jsonl"
stats = {"snapshots": 0, "last_ok": None, "remaining_credits": None}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(stats).encode("utf-8"))

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logging.info(f"Health server listening on :{port}")


def compress_states(states: list) -> str:
    raw = json.dumps(states, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, compresslevel=6)).decode("ascii")


def fetch_opensky(endpoint: str, params: dict):
    try:
        resp = requests.get(f"{BASE_URL}{endpoint}", params=params, auth=AUTH, timeout=20)
        if resp.status_code == 200:
            return resp.json(), resp.headers.get("X-Rate-Limit-Remaining")
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("X-Rate-Limit-Retry-After-Seconds", 60))
            logging.warning(f"Rate limited on {endpoint}, sleeping {retry_after}s")
            time.sleep(retry_after)
        else:
            logging.warning(f"HTTP {resp.status_code} on {endpoint}: {resp.text[:120]}")
    except requests.RequestException as e:
        logging.error(f"Request error on {endpoint}: {e}")
    return None, None


def buffer_record(table: str, payload: dict):
    with open(FALLBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"table": table, "data": payload}) + "\n")


def flush_buffer():
    if not os.path.exists(FALLBACK_FILE):
        return
    with open(FALLBACK_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    failed = []
    for line in lines:
        item = json.loads(line)
        try:
            if item["table"] == "raw_state_snapshots":
                supabase.table("raw_state_snapshots").insert(item["data"]).execute()
            elif item["table"] == "raw_ltfm_arrivals":
                supabase.table("raw_ltfm_arrivals").upsert(
                    item["data"], on_conflict="icao24,first_seen,last_seen"
                ).execute()
        except Exception:
            failed.append(line)

    if failed:
        with open(FALLBACK_FILE, "w", encoding="utf-8") as f:
            f.writelines(failed)
    else:
        os.remove(FALLBACK_FILE)
        logging.info("Flushed local buffer to Supabase")


def poll_states():
    acq_utc = datetime.now(timezone.utc).timestamp()
    data, remaining = fetch_opensky("/states/all", BBOX_PARAMS)
    if data is None:
        return

    states = data.get("states") or []
    row = {
        "acquisition_utc": acq_utc,
        "opensky_time": data.get("time"),
        "aircraft_count": len(states),
        "states_gz_b64": compress_states(states),
    }

    try:
        supabase.table("raw_state_snapshots").insert(row).execute()
        stats["snapshots"] += 1
        stats["last_ok"] = datetime.now(timezone.utc).isoformat()
        stats["remaining_credits"] = remaining
        logging.info(f"States saved | aircraft={len(states)} | credits={remaining}")
    except Exception as e:
        logging.error(f"Supabase insert failed: {e}")
        buffer_record("raw_state_snapshots", row)


def poll_arrivals():
    now_ts = int(datetime.now(timezone.utc).timestamp())
    params = {"airport": "LTFM", "begin": now_ts - 7200, "end": now_ts}
    acq_utc = datetime.now(timezone.utc).timestamp()
    data, remaining = fetch_opensky("/flights/arrival", params)
    if not data:
        return

    rows = []
    for item in data:
        icao24 = item.get("icao24")
        first_seen = item.get("firstSeen")
        last_seen = item.get("lastSeen")
        if not (icao24 and first_seen and last_seen):
            continue
        rows.append({
            "acquisition_utc": acq_utc,
            "window_begin": params["begin"],
            "window_end": params["end"],
            "icao24": icao24,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "est_departure_airport": item.get("estDepartureAirport"),
            "est_arrival_airport": item.get("estArrivalAirport"),
            "callsign": (item.get("callsign") or "").strip(),
            "raw_payload": item,
        })

    if not rows:
        return

    try:
        supabase.table("raw_ltfm_arrivals").upsert(
            rows, on_conflict="icao24,first_seen,last_seen"
        ).execute()
        logging.info(f"Arrivals saved | count={len(rows)} | credits={remaining}")
    except Exception as e:
        logging.error(f"Supabase arrivals upsert failed: {e}")
        for r in rows:
            buffer_record("raw_ltfm_arrivals", r)


def main():
    start_health_server()
    logging.info("Starting LTFM OpenSky collector")
    last_arrival_poll = 0.0

    while True:
        t0 = time.monotonic()
        flush_buffer()

        if time.time() - last_arrival_poll >= ARRIVAL_INTERVAL:
            poll_arrivals()
            last_arrival_poll = time.time()

        poll_states()

        elapsed = time.monotonic() - t0
        time.sleep(max(1.0, POLL_INTERVAL - elapsed))


if __name__ == "__main__":
    main()
