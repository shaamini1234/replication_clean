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
import os
import queue
import threading
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests

from _neon import NEON_URL as NEON
KEYS_FILE = Path.home() / "ch_api_keys.txt"
API       = "https://api.company-information.service.gov.uk/company/{}"
LOG_DIR   = Path.home() / "ch_extract"
LOG_FILE  = LOG_DIR / "ch_extract.log"

# Per-key pacing. CH allows 600 req / 5 min PER APPLICATION (measured: each key
# carries its own budget). 0.55s = 545/5min, just under. Raise the interval or
# drop CH_MAX_KEYS if Companies House starts rejecting: on 2026-09-14 and
# 2026-09-15, 7 keys at a 12.7 req/s aggregate from one IP were all rejected
# 401/403 in the same second, ~262s into the run, while each key was still
# individually under budget.
PER_KEY_INTERVAL = float(os.environ.get("CH_PER_KEY_INTERVAL", "0.55"))
MAX_KEYS   = int(os.environ.get("CH_MAX_KEYS", "0"))   # 0 = use every key
BATCH      = 100
DB_BACKOFF = [5, 15, 30, 60, 120, 300]
# A 401/403 pauses that worker rather than killing it, so a temporary block
# costs minutes instead of the whole run.
AUTH_BACKOFF   = [300, 600, 1200, 1800]
AUTH_RESET_OKS = 500   # consecutive successes that clear a worker's strikes

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=3)])
log = logging.getLogger(__name__)

KEYS = [k.strip() for k in KEYS_FILE.read_text().splitlines() if k.strip()]
if not KEYS:
    raise SystemExit(f"no API keys in {KEYS_FILE}")
AVAILABLE = len(KEYS)
if MAX_KEYS:
    KEYS = KEYS[:MAX_KEYS]
log.info("using %d of %d API key(s) — %d workers at %.2fs/key (~%.1f req/s total)",
         len(KEYS), AVAILABLE, len(KEYS), PER_KEY_INTERVAL, len(KEYS) / PER_KEY_INTERVAL)

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

todo_q    = queue.Queue(maxsize=20000)  # bounded: stream, don't load 3.7M into RAM
SENTINEL  = object()
_counter  = {"n": 0, "total": 0}
_lock     = threading.Lock()
_shutdown = threading.Event()   # set once every worker has stopped, so the
                                # feeder can't block forever on a full queue
_drained  = threading.Event()   # set when the feeder has streamed the WHOLE
                                # queue: the difference between "finished" and
                                # "died early", which the supervisor needs to
                                # know so it stops relaunching us
DONE_FILE = LOG_DIR / "COMPLETE"


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


# Two passes, so we NEVER sort the full multi-million queue:
#   recent insolvencies first (small, uses the death_date index), then
#   everything else (strike-off candidates), streamed unsorted
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
    try:
        for i, sql in enumerate(FEED_PHASES):
            cur = conn.cursor(name=f"todo_pass_{i}")  # server-side streaming cursor
            cur.itersize = 10000
            cur.execute(sql)
            for (num,) in cur:
                # Offer with a timeout rather than blocking forever: if every
                # worker has stopped, nothing drains the queue and an
                # unconditional put() would hang the process (it did, on
                # 2026-09-15 — the run sat idle for 17 minutes).
                while not _shutdown.is_set():
                    try:
                        todo_q.put(num, timeout=5)
                        break
                    except queue.Full:
                        continue
                if _shutdown.is_set():
                    log.info("feeder stopping — no workers left")
                    cur.close()
                    return
            cur.close()
    finally:
        conn.close()
    _drained.set()               # every row streamed — this was a clean finish
    for _ in KEYS:               # one sentinel per worker to signal end
        try:
            todo_q.put(SENTINEL, timeout=5)
        except queue.Full:
            log.warning("could not deliver stop signal — queue full")


def _limits(r):
    """Companies House rate-limit headers, for diagnosing a block."""
    h = r.headers
    return ("ratelimit limit=%s remain=%s reset=%s window=%s" % (
        h.get("x-ratelimit-limit"), h.get("x-ratelimit-remain"),
        h.get("x-ratelimit-reset"), h.get("x-ratelimit-window")))


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
            retry_after = int(r.headers.get("Retry-After", 60))
            log.warning("key …%s 429 rate-limited — sleeping %ds (%s)",
                        key[-4:], retry_after, _limits(r))
            time.sleep(retry_after); continue
        if r.status_code in (401, 403):
            # Log what Companies House actually said — without this the cause of
            # a block is unknowable after the fact. Never log the key itself.
            log.error("key …%s HTTP %d — %s — body=%.300s",
                      key[-4:], r.status_code, _limits(r),
                      r.text.replace("\n", " "))
            raise AuthFail(key)
        log.warning("key …%s unexpected HTTP %d for %s — skipping",
                    key[-4:], r.status_code, num)
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
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as write_err:
            log.warning("DB write failed (%s) — reconnecting",
                        str(write_err).splitlines()[0])
            try:
                conn.close()
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as close_err:
                log.warning("closing dead DB connection failed: %s", close_err)
            conn = connect()
    raise RuntimeError("DB write failed")


def worker(key):
    conn = connect()
    buf, last = [], 0.0
    tag = key[-4:]
    strikes, oks = 0, 0
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
            # Flush first: those rows are already paid for in requests.
            if buf:
                conn = flush(conn, buf); buf = []
            todo_q.put(num)
            if strikes >= len(AUTH_BACKOFF):
                log.error("key …%s rejected %d times — retiring this worker", tag, strikes)
                break
            pause = AUTH_BACKOFF[strikes]
            strikes += 1
            oks = 0
            log.warning("key …%s rejected — pausing %ds (strike %d of %d)",
                        tag, pause, strikes, len(AUTH_BACKOFF))
            if _shutdown.wait(pause):
                break
            continue
        oks += 1
        if oks >= AUTH_RESET_OKS and strikes:
            log.info("key …%s recovered — clearing strikes", tag)
            strikes, oks = 0, 0
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
    # Join the WORKERS first, then release the feeder. The old order (feed.join()
    # first) deadlocked whenever every worker exited early: the feeder blocked
    # forever pushing into a queue nobody was draining.
    for t in workers:
        t.join()
    _shutdown.set()
    feed.join(timeout=30)
    if feed.is_alive():
        log.warning("feeder did not stop within 30s — exiting anyway")
    if _drained.is_set():
        DONE_FILE.write_text(f"queue drained at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.info("=== extraction COMPLETE: %d processed this run ===", _counter["n"])
    else:
        log.warning("=== extraction stopped EARLY: %d processed this run "
                    "(queue not drained — supervisor should relaunch) ===",
                    _counter["n"])


if __name__ == "__main__":
    main()
