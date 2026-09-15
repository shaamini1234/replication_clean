#!/usr/bin/env python3
"""sp500_edgar_sector_fetch.py — recover sector/SIC for delisted S&P constituents.

Why this exists
---------------
``sp500_companies_full`` carries GICS ``sector`` only for CURRENT index members
(it derives from the live constituent list). Every company that LEFT the index
has no sector — 578 of 1,049 symbols. That is survivorship bias in the one field
the sector analysis depends on, and it is worst for exactly the cohort of most
interest: the dot-com tech entrants, nearly all of which later exited.

SEC EDGAR retains CIK, company name and SIC for delisted registrants
indefinitely, so the gap is recoverable. This script walks every symbol that has
a CIK but no sector, reads the EDGAR submissions API, and writes the recovered
facts to ``source_inputs/sp500_edgar_sector_enrichment.csv`` with a source URL
per row.

It writes a CSV and nothing else — applying it to the database is
``apply_sector_enrichment.py``'s job, so this step stays re-runnable and the
recovered data stays reviewable before it lands anywhere.

API contract (validated 2026-09-15)
-----------------------------------
GET https://data.sec.gov/submissions/CIK##########.json  (CIK zero-padded to 10)
  -> {"cik","name","sic","sicDescription","formerNames":[...],"tickers":[...],
      "entityType","stateOfIncorporation", ...}
No auth. A descriptive User-Agent is required by SEC fair-access policy; the
documented ceiling is 10 requests/second.
    https://www.sec.gov/search-filings/edgar-application-programming-interfaces

Note: ``tickers`` is EMPTY for delisted registrants, so the ticker->CIK
direction does not work for them. CIK->facts does, which is why this script is
driven by the CIKs the project already holds.

Usage:
    python python/sp500_edgar_sector_fetch.py            # fetch what's missing
    python python/sp500_edgar_sector_fetch.py --all      # refetch every symbol
    python python/sp500_edgar_sector_fetch.py --limit 20 # smoke test
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import duckdb

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from sic_gics_map import SECTORS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
OUT = REPO / "source_inputs" / "sp500_edgar_sector_enrichment.csv"
CACHE = REPO / "source_inputs" / ".edgar_cache"

# SEC fair-access: documented ceiling is 10 req/s. We sit well under it.
SLEEP = 0.15
UA = os.environ.get(
    "SEC_USER_AGENT", "British Progress Research shaamini@britishprogress.org"
)
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def targets(all_symbols: bool) -> list[tuple[str, int, str]]:
    """(symbol, cik, existing_sector) for every symbol holding a CIK.

    Default: symbols whose sector is UNUSABLE — either NULL, or a value outside
    the 11-sector GICS vocabulary. The second case matters: the ``sector`` column
    carries a SIC description for ~143 symbols (e.g. "Crude Petroleum & Natural
    Gas"), which every downstream query silently discards because it filters on
    the vocabulary. Those rows look populated but behave as missing, so they need
    recovering too.

    --all: every symbol with a CIK, so an existing sector can be cross-checked
    against EDGAR's SIC.
    """
    con = duckdb.connect(DB, read_only=True)
    vocab = "','".join(sorted(SECTORS))
    having = "" if all_symbols else f"and (f.sector is null or f.sector not in ('{vocab}'))"
    # CIK comes from sp500_identity, the canonical crosswalk — never from a
    # ticker lookup. See build_identity_crosswalk.py: sp500_companies_full holds
    # the WRONG company for seven reused tickers (Compuware/Ocean Thermal etc).
    rows = con.execute(
        f"""
        with f as (select symbol, max(sector) sector from sp500_companies_full group by 1)
        select i.symbol, i.cik, f.sector
        from sp500_identity i
        left join f on f.symbol = i.symbol
        where i.cik is not null {having}
        order by i.symbol
        """
    ).fetchall()
    con.close()
    out = []
    for sym, cik, sector in rows:
        try:
            out.append((sym, int(cik), sector or ""))
        except (TypeError, ValueError):
            print(f"  skip {sym}: unparseable CIK {cik!r}", file=sys.stderr)
    return out


def fetch(cik: int) -> dict | None:
    """EDGAR submissions for one CIK. Cached on disk; None on a hard failure."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"CIK{cik:010d}.json"
    if cached.exists():
        try:
            return json.loads(cached.read_text())
        except json.JSONDecodeError:
            cached.unlink()  # corrupt cache entry — refetch below

    req = urllib.request.Request(
        SUBMISSIONS.format(cik=cik), headers={"User-Agent": UA, "Accept-Encoding": "gzip"}
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            d = json.loads(body)
            # Store only the fields we use — the filings arrays are megabytes.
            keep = {k: d.get(k) for k in
                    ("cik", "name", "sic", "sicDescription", "formerNames",
                     "tickers", "entityType", "stateOfIncorporation")}
            cached.write_text(json.dumps(keep))
            return keep
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                      # CIK genuinely absent from EDGAR
            if e.code in (429, 503) and attempt < 2:
                time.sleep(2 ** attempt)          # backoff, then retry
                continue
            print(f"  CIK {cik}: HTTP {e.code}", file=sys.stderr)
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            print(f"  CIK {cik}: {type(e).__name__} {e}", file=sys.stderr)
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="refetch every symbol holding a CIK")
    ap.add_argument("--limit", type=int, default=0, help="stop after N symbols (smoke test)")
    args = ap.parse_args()

    tg = targets(args.all)
    if args.limit:
        tg = tg[: args.limit]
    print(f"symbols to fetch: {len(tg)}  (cache: {CACHE})")

    rows, miss, nosic = [], 0, 0
    for i, (sym, cik, existing) in enumerate(tg, 1):
        d = fetch(cik)
        if d is None:
            miss += 1
        else:
            sic = (d.get("sic") or "").strip()
            if not sic:
                nosic += 1
            rows.append({
                "symbol": sym,
                "cik": f"{cik:010d}",
                "edgar_name": d.get("name") or "",
                "sic": sic,
                "sic_description": d.get("sicDescription") or "",
                "entity_type": d.get("entityType") or "",
                "state_of_inc": d.get("stateOfIncorporation") or "",
                "former_names": "; ".join(
                    fn.get("name", "") for fn in (d.get("formerNames") or []) if fn.get("name")
                ),
                "existing_sector": existing,
                "source_url": SUBMISSIONS.format(cik=cik),
                "retrieved": time.strftime("%Y-%m-%d"),
            })
        if i % 50 == 0 or i == len(tg):
            print(f"  {i}/{len(tg)}  ok={len(rows)} missing={miss} no_sic={nosic}")
        time.sleep(SLEEP)

    if not rows:
        print("no rows fetched — nothing written", file=sys.stderr)
        return 1

    # MERGE, never replace. `targets()` is incremental against the current
    # database state, so once the enrichment has been applied it returns almost
    # nothing — a plain overwrite would truncate the durable record to whatever
    # this run happened to fetch. Existing rows are keyed on CIK and kept unless
    # this run refetched them.
    merged: dict[str, dict] = {}
    if OUT.exists():
        with OUT.open(newline="") as f:
            for r in csv.DictReader(f):
                if r.get("cik"):
                    merged[r["cik"]] = r
    kept = len(merged)
    for r in rows:
        merged[r["cik"]] = r
    out_rows = [merged[k] for k in sorted(merged)]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    # One row per CIK, not per ticker: share classes and renames (GOOG/GOOGL,
    # FB/META) are one company and collapse to one row by design.
    fetched_ciks = {r["cik"] for r in rows}
    print(f"\nwrote {OUT}: {len(out_rows)} rows (one per CIK)")
    print(f"  {len(rows)} symbols fetched this run -> {len(fetched_ciks)} distinct companies")
    print(f"  {len(out_rows) - len(fetched_ciks)} rows carried over from the previous file ({kept} rows)")
    print(f"  {miss} CIKs not in EDGAR; {nosic} of this run's rows had no SIC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
