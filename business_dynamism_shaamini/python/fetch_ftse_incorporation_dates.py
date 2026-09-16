#!/usr/bin/env python3
"""fetch_ftse_incorporation_dates.py — get birth dates for FTSE constituents.

Filling the missing company numbers on ftse100_membership resolved every
`historical_no_ch_number` entrant, but moved them to `unknown_age`: they now
have a registered identity and no incorporation date, so age at index entry
cannot be computed and they fall out of the entrant classification entirely.

The dates are a direct Companies House lookup on numbers that are now known.
Results are written to ``source_inputs/ftse_incorporation_dates.csv`` with the
Companies House URL per row, then applied to ``ftse100_consolidated``.

Usage:
    python python/fetch_ftse_incorporation_dates.py
    python python/fetch_ftse_incorporation_dates.py --apply-only
"""
from __future__ import annotations
import argparse, base64, csv, itertools, json, os, time, urllib.error, urllib.request
from pathlib import Path
import duckdb

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
OUT = REPO / "source_inputs" / "ftse_incorporation_dates.csv"
KEYS = [k.strip() for k in (Path.home() / "ch_api_keys.txt").read_text().splitlines() if k.strip()]
CYC = itertools.cycle(KEYS)
CH = "https://find-and-update.company-information.service.gov.uk/company/"


def get(cn: str):
    time.sleep(0.6 / max(len(KEYS), 1))
    auth = "Basic " + base64.b64encode((next(CYC) + ":").encode()).decode()
    try:
        req = urllib.request.Request(
            f"https://api.company-information.service.gov.uk/company/{cn}",
            headers={"Authorization": auth, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply-only", action="store_true", help="skip fetching, apply the existing CSV")
    args = ap.parse_args()
    con = duckdb.connect(DB, read_only=False)

    if not args.apply_only:
        targets = [r[0] for r in con.execute("""
            select distinct m.company_number
            from ftse100_membership m
            left join ftse100_consolidated f on f.company_number = m.company_number
            where m.company_number is not null
            group by m.company_number
            having max(f.incorporation_date) is null
        """).fetchall()]
        print(f"FTSE companies with a number but no incorporation date: {len(targets)}")
        rows, miss = [], 0
        for i, cn in enumerate(targets, 1):
            d = get(cn)
            if not d or not d.get("date_of_creation"):
                miss += 1
            else:
                rows.append({"company_number": cn,
                             "company_name": d.get("company_name", ""),
                             "incorporation_date": d["date_of_creation"],
                             "company_status": d.get("company_status", ""),
                             "source_url": CH + cn,
                             "retrieved": time.strftime("%Y-%m-%d")})
            if i % 25 == 0 or i == len(targets):
                print(f"  {i}/{len(targets)}  found {len(rows)}  missing {miss}")
        if rows:
            with OUT.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
            print(f"\nwrote {OUT.name}: {len(rows)} dates")

    if not OUT.exists():
        print("no dates file to apply"); con.close(); return 1
    con.execute(f"create or replace temp view inc as "
                f"select * from read_csv_auto('{OUT}', header=true, all_varchar=true)")
    before = con.execute("select count(*) from ftse100_consolidated where incorporation_date is null").fetchone()[0]
    con.execute("""update ftse100_consolidated t set incorporation_date = try_cast(i.incorporation_date as date)
                   from inc i where i.company_number = t.company_number and t.incorporation_date is null""")
    after = con.execute("select count(*) from ftse100_consolidated where incorporation_date is null").fetchone()[0]
    print(f"\nftse100_consolidated rows without an incorporation date: {before} -> {after}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
