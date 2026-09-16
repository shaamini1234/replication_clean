#!/usr/bin/env python3
"""apply_ftse_company_numbers.py — fill the missing company numbers on FTSE membership.

149 ftse100_membership rows (115 distinct names) carried no company_number, so
they could not join to Companies House, to the firm-year panel, or to anything
else keyed on the registered entity.

Where the numbers came from
---------------------------
Every number here is carried from an existing adjudicated decision, not derived
by fuzzy search. Precedence, highest first:

  1. ch_crosswalk_adjudicated.csv / ch_map.csv  — the prior name-to-number review,
     taking only ACCEPTED* and CONFIRMED verdicts. PROPOSED is a candidate, not a
     decision, and is not used.
  2. FTSE100_CANONICAL_DATABASE               — matched on company_name or
     former_names in the project's own curated record.
  3. ftse100_consolidated                     — same, as a last resort.

Three constituents are recorded as NOT_UK: Randgold Resources and Polymetal
International are Jersey-registered and Resolution is a different company from
the UK Resolution plc. They have no Companies House number and the null is
correct, not missing.

What is deliberately NOT done
-----------------------------
A Companies House name search returns confident-looking matches that are wrong:
"Eastern Electricity" matches a company incorporated in 2023, "Midland Bank"
matches a nominee company, "Glencore" matches a dissolved UK subsidiary rather
than the Jersey-registered plc. Attaching membership history to those would be
worse than leaving the field null, so none of them are applied. 55 names remain
unresolved and are left null.

This mirrors the reasoning already recorded in company_number_review.csv, which
removed numbers on exactly these grounds -- including the Scottish & Newcastle
row that was matched to Smith & Nephew's 00324357.

Usage:
    python python/apply_ftse_company_numbers.py --dry-run
    python python/apply_ftse_company_numbers.py
"""
from __future__ import annotations
import argparse, csv, os, re, sys
from pathlib import Path
import duckdb

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
SRC = REPO / "source_inputs" / "ftse_membership_company_numbers.csv"
SUFFIX = re.compile(r"\b(plc|p l c|limited|ltd|group|holdings|company|the|co|international|corporation|corp|inc)\b")


def norm(s: str | None) -> str:
    s = (s or "").lower().replace("&", " and ").replace(".", " ")
    return re.sub(r"[^a-z0-9]", "", SUFFIX.sub(" ", s))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not SRC.exists():
        print(f"missing {SRC}", file=sys.stderr); return 1

    mapping, notuk = {}, {}
    for r in csv.DictReader(SRC.open(newline="")):
        k = norm(r["ftse_name"])
        if r["resolution_source"] == "NOT_UK":
            notuk[k] = r["ftse_name"]
        elif r["company_number"].strip():
            mapping[k] = (r["company_number"].strip(), r["resolution_source"])

    con = duckdb.connect(DB, read_only=args.dry_run)
    rows = con.execute(
        "select rowid, company_name from ftse100_membership where company_number is null"
    ).fetchall()
    hits = [(rid, nm, *mapping[norm(nm)]) for rid, nm in rows if norm(nm) in mapping]
    nuk = [(rid, nm) for rid, nm in rows if norm(nm) in notuk]

    print(f"membership rows with no company_number : {len(rows)}")
    print(f"  fillable from adjudicated sources     : {len(hits)}")
    print(f"  confirmed NOT_UK (null is correct)    : {len(nuk)}")
    print(f"  left null, unresolved                 : {len(rows) - len(hits) - len(nuk)}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        for rid, nm, cn, src in hits[:8]:
            print(f"    {nm[:30]:32s} -> {cn:10s} ({src})")
        con.close(); return 0

    cols = {r[0] for r in con.execute(
        "select column_name from information_schema.columns where table_name = 'ftse100_membership'").fetchall()}
    if "company_number_source" not in cols:
        con.execute("alter table ftse100_membership add column company_number_source VARCHAR")
    for rid, nm, cn, src in hits:
        con.execute("update ftse100_membership set company_number = ?, company_number_source = ? "
                    "where rowid = ?", [cn, src, rid])
    for rid, nm in nuk:
        con.execute("update ftse100_membership set company_number_source = 'NOT_UK' where rowid = ?", [rid])

    left = con.execute("select count(*) from ftse100_membership where company_number is null").fetchone()[0]
    print(f"\n  applied. rows still without a number: {left} (was {len(rows)})")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
