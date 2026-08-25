#!/usr/bin/env bash
# ============================================================================
# deploy_ch_server.sh — run the Companies House extraction on a cloud VM,
# unattended, under systemd (survives reboots). For Oracle Cloud / GCP free tier.
#
# ONE-TIME on a fresh Ubuntu VM:
#   1) put your CH API key(s) in place, ONE PER LINE (more keys = proportionally
#      faster; 1 key ≈ weeks, 10 keys ≈ a few days):
#        nano ~/ch_api_keys.txt        # paste key(s), save
#   2) run this script:
#        bash deploy_ch_server.sh
#   3) watch it:
#        journalctl -u chextract -f
# It's resumable — skips the ~354k already done and continues the Neon queue.
# ============================================================================
set -euo pipefail
USER_NAME="$(whoami)"
HOME_DIR="$HOME"

if [ ! -s "$HOME_DIR/ch_api_keys.txt" ]; then
  echo "ERROR: $HOME_DIR/ch_api_keys.txt is missing or empty."
  echo "Create it first:  nano ~/ch_api_keys.txt   (one CH API key per line)"
  exit 1
fi
echo ">> $(wc -l < "$HOME_DIR/ch_api_keys.txt") API key(s) found"

echo ">> installing python + deps"
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip
pip3 install --break-system-packages requests psycopg2-binary 2>/dev/null || pip3 install requests psycopg2-binary

echo ">> writing extractor to $HOME_DIR/ch_api_extract.py"
cat > "$HOME_DIR/ch_api_extract.py" <<'PYEOF'
#!/usr/bin/env python3
"""
ch_api_extract.py — look up dead companies in the Companies House API to recover
incorporation date (BIRTH), dissolution date, status and SIC (industry).

CONCURRENT version: one worker thread per API key, each key paced just under its
600-requests/5-min limit. With 3 keys this runs ~3x faster than single-threaded
(~1 day for ~480k companies).

Reads the queue from Neon (ch_lookup_queue), writes to Neon (ch_company_profile).
Resumable (skips done), crash-resilient (systemd restart), rate-limit aware.
Keys in ~/ch_api_keys.txt (one per line).
"""
import logging
import logging.handlers
import queue
import threading
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests

NEON = ("postgresql://neondb_owner:npg_q1uDNWofte0n"
        "@ep-nameless-fire-atkh5lxj.c-9.us-east-1.aws.neon.tech"
        "/neondb?sslmode=require")
KEYS_FILE = Path.home() / "ch_api_keys.txt"
API       = "https://api.company-information.service.gov.uk/company/{}"
LOG_DIR   = Path.home() / "ch_extract"
LOG_FILE  = LOG_DIR / "ch_extract.log"

PER_KEY_INTERVAL = 0.55    # s between requests on ONE key (<2/s => <600/5min)
BATCH      = 100
DB_BACKOFF = [5, 15, 30, 60, 120, 300]

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=3)])
log = logging.getLogger(__name__)

KEYS = [k.strip() for k in KEYS_FILE.read_text().splitlines() if k.strip()]
if not KEYS:
    raise SystemExit(f"no API keys in {KEYS_FILE}")
log.info("loaded %d API key(s) — %d concurrent workers", len(KEYS), len(KEYS))

INSERT_SQL = """
INSERT INTO ch_company_profile
  (company_number, incorporation_date, dissolution_date,
   company_status, company_type, sic_codes, not_found)
VALUES %s
ON CONFLICT (company_number) DO UPDATE SET
  incorporation_date = EXCLUDED.incorporation_date,
  dissolution_date   = EXCLUDED.dissolution_date,
  company_status     = EXCLUDED.company_status,
  company_type       = EXCLUDED.company_type,
  sic_codes          = EXCLUDED.sic_codes,
  not_found          = EXCLUDED.not_found,
  fetched_at         = now()
"""

todo_q   = queue.Queue(maxsize=20000)   # bounded: stream, don't load 3.7M into RAM
SENTINEL = object()
_counter = {"n": 0, "total": 0}
_lock    = threading.Lock()


class AuthFail(Exception):
    pass


def connect():
    for wait in [0] + DB_BACKOFF:
        if wait:
            log.warning("DB connect retry in %ds", wait); time.sleep(wait)
        try:
            return psycopg2.connect(NEON, options="-c search_path=public")
        except psycopg2.OperationalError as e:
            log.warning("DB connect failed: %s", str(e).splitlines()[0])
    raise RuntimeError("DB unreachable")


def ensure_tables(conn):
    with conn.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS ch_company_profile(
            company_number     text PRIMARY KEY,
            incorporation_date date,
            dissolution_date   date,
            company_status     text,
            company_type       text,
            sic_codes          text,
            not_found          boolean DEFAULT false,
            fetched_at         timestamptz DEFAULT now())""")
    conn.commit()


def count_todo(conn):
    # cheap estimate (avoids a slow anti-join count over millions)
    with conn.cursor() as c:
        c.execute("SELECT (SELECT count(*) FROM ch_lookup_queue) "
                  "- (SELECT count(*) FROM ch_company_profile)")
        return max(c.fetchone()[0], 0)


# Two phases, so we NEVER sort the full multi-million queue:
#   phase 1 = recent insolvencies first (small, uses the death_date index)
#   phase 2 = everything else (strike-off candidates), streamed unsorted
FEED_PHASES = [
    """SELECT q.company_number FROM ch_lookup_queue q
         LEFT JOIN ch_company_profile p USING (company_number)
         WHERE p.company_number IS NULL AND q.death_date IS NOT NULL
         ORDER BY q.death_date DESC""",
    """SELECT q.company_number FROM ch_lookup_queue q
         LEFT JOIN ch_company_profile p USING (company_number)
         WHERE p.company_number IS NULL AND q.death_date IS NULL""",
]


def feeder():
    """Stream not-yet-done numbers into the bounded queue via server-side
    cursors, so we never hold millions of rows in RAM and never sort them all."""
    conn = connect()
    for i, sql in enumerate(FEED_PHASES):
        cur = conn.cursor(name=f"todo_phase_{i}")   # server-side streaming cursor
        cur.itersize = 10000
        cur.execute(sql)
        for (num,) in cur:
            todo_q.put(num)      # blocks when full -> bounded memory
        cur.close()
    conn.close()
    for _ in KEYS:               # one sentinel per worker to signal end
        todo_q.put(SENTINEL)


def fetch(num, key):
    """Return JSON dict, or None if not found. Raise AuthFail if the key is bad."""
    tries = 0
    while True:
        try:
            r = requests.get(API.format(num), auth=(key, ""), timeout=30)
        except requests.RequestException:
            tries += 1
            if tries >= 5:
                return None
            time.sleep(5); continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 60))); continue
        if r.status_code in (401, 403):
            raise AuthFail(key)
        return None


def parse(num, j):
    if j is None:
        return (num, None, None, None, None, None, True)
    sic = j.get("sic_codes") or []
    return (num,
            j.get("date_of_creation")  or None,
            j.get("date_of_cessation") or None,
            j.get("company_status")    or None,
            j.get("type")              or None,
            ",".join(sic) if sic else None,
            False)


def flush(conn, rows):
    for wait in [0] + DB_BACKOFF:
        if wait:
            time.sleep(wait)
        try:
            with conn.cursor() as c:
                psycopg2.extras.execute_values(c, INSERT_SQL, rows, page_size=BATCH)
            conn.commit()
            return conn
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            try: conn.close()
            except Exception: pass
            conn = connect()
    raise RuntimeError("DB write failed")


def worker(key):
    conn = connect()
    buf, last = [], 0.0
    tag = key[-4:]
    while True:
        num = todo_q.get()          # blocks until work or sentinel
        if num is SENTINEL:
            break
        dt = time.time() - last
        if dt < PER_KEY_INTERVAL:
            time.sleep(PER_KEY_INTERVAL - dt)
        last = time.time()
        try:
            data = fetch(num, key)
        except AuthFail:
            log.error("key …%s rejected (401/403) — stopping this worker; requeueing", tag)
            todo_q.put(num)
            break
        buf.append(parse(num, data))
        with _lock:
            _counter["n"] += 1
            n, total = _counter["n"], _counter["total"]
        if len(buf) >= BATCH:
            conn = flush(conn, buf); buf = []
        if n % 500 == 0:
            log.info("%d / %d done (%.1f%%)", n, total, 100 * n / total)
    if buf:
        conn = flush(conn, buf)
    conn.close()


def main():
    conn = connect()
    ensure_tables(conn)
    _counter["total"] = count_todo(conn)
    conn.close()
    log.info("to look up: %d companies across %d workers (streaming)", _counter["total"], len(KEYS))

    feed = threading.Thread(target=feeder, daemon=True)
    feed.start()
    workers = [threading.Thread(target=worker, args=(k,), daemon=True) for k in KEYS]
    for t in workers:
        t.start()
    feed.join()
    for t in workers:
        t.join()
    log.info("=== extraction complete: %d processed ===", _counter["n"])


if __name__ == "__main__":
    main()
PYEOF

echo ">> installing systemd service (auto-restart, survives reboot)"
sudo tee /etc/systemd/system/chextract.service >/dev/null <<UNIT
[Unit]
Description=Companies House extraction
After=network-online.target
Wants=network-online.target
[Service]
User=${USER_NAME}
WorkingDirectory=${HOME_DIR}
ExecStart=$(command -v python3) ${HOME_DIR}/ch_api_extract.py
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now chextract
sleep 8
sudo systemctl status chextract --no-pager || true
echo
echo ">> DONE. Follow progress with:  journalctl -u chextract -f"
echo ">> It runs unattended and restarts on reboot. Nothing else to do."
