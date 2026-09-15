#!/usr/bin/env python3
"""apply_ftse_membership_corrections.py — land the FTSE Russell corrections.

Applies the replacement-sourcing results in
``deliverables/lseg_sourced_data_for_replacement_FILLED.csv`` to
``ftse100_membership``, the authoritative record of FTSE 100 entry and exit
dates that every downstream build reads.

Five classes of change
----------------------
1. **Spurious founding rows, real entry exists (9).** The spine dated these
   companies to the index launch, but the provider record shows them first
   entering years later AND the correct episode is already present. The
   1984-01-02 row is deleted.

2. **Spurious founding rows, no real entry row (10).** Same error, but the
   later episode is missing, so the founding row is re-dated to the real first
   entry and its entry_type becomes 'added'.

3. **Genuine founding members (~125).** These carry 1984-01-02, which is a
   placeholder: the FTSE 100 launched on 1984-01-03. Moved to the real date.

4. **Unsupported exits (2).** British Land 2025-12-22 is an ENTRY in the
   provider record (WPP was the deletion), and no Wolseley exit exists on
   2013-06-24. Both end_dates are cleared rather than left asserting an event
   the record does not contain.

5. **Citation (all LSEG-derived rows).** source_url is set to the public
   FTSE Russell document, so every date carries a link a reader can follow
   instead of a reference to a licensed PDF with no URL.

Usage:
    python python/apply_ftse_membership_corrections.py --dry-run
    python python/apply_ftse_membership_corrections.py
"""
from __future__ import annotations
import argparse, csv, os, sys
from pathlib import Path
import duckdb

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
FILLED = REPO / "deliverables" / "lseg_sourced_data_for_replacement_FILLED.csv"
BACKUP = REPO / "source_inputs" / "ftse100_membership_backup_pre_corrections.csv"

PUBLIC_URL = ("https://www.lseg.com/content/dam/ftse-russell/en_us/documents/"
              "policy-documents/ftse-100-constituent-history.pdf")
CITATION = "FTSE Russell (LSEG), FTSE 100 Historic Additions and Deletions, August 2026"
LAUNCH_PLACEHOLDER = "1984-01-02"
LAUNCH_REAL = "1984-01-03"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not FILLED.exists():
        print(f"missing {FILLED}", file=sys.stderr); return 1
    rows = list(csv.DictReader(FILLED.open(newline="")))
    con = duckdb.connect(DB, read_only=args.dry_run)

    # classify the launch-placeholder corrections
    delete_founding, redate_founding = [], []
    for r in rows:
        if r["current_value"][:10] != LAUNCH_PLACEHOLDER: continue
        if r["agrees_with_current"] != "no" or not r["replacement_value"].strip(): continue
        cn, real = r["company_number"], r["replacement_value"][:10]
        eps = con.execute(
            "select cast(start_date as varchar) from ftse100_membership where company_number = ?", [cn]
        ).fetchall()
        starts = {s for (s,) in eps}
        (delete_founding if real in starts else redate_founding).append((cn, real, r["company_name"]))

    clear_exit = [(r["company_number"], r["company_name"])
                  for r in rows
                  if r["field"] == "ftse_exit_date" and r["agrees_with_current"] == "no"
                  and not r["replacement_value"].strip()]

    n_launch = con.execute(
        "select count(*) from ftse100_membership where cast(start_date as varchar) = ?", [LAUNCH_PLACEHOLDER]
    ).fetchone()[0]

    print(f"ftse100_membership: {con.execute('select count(*) from ftse100_membership').fetchone()[0]} rows")
    print(f"  delete spurious founding row (real episode present) : {len(delete_founding)}")
    print(f"  re-date spurious founding row (no real episode)     : {len(redate_founding)}")
    print(f"  genuine founding members to move to {LAUNCH_REAL}    : {n_launch - len(delete_founding) - len(redate_founding)}")
    print(f"  exits to clear (event not in the record)            : {len(clear_exit)}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        for cn, real, nm in redate_founding[:5]:
            print(f"    would re-date {nm[:26]:28s} {LAUNCH_PLACEHOLDER} -> {real}")
        con.close(); return 0

    # one-time backup of the table as it stands
    if not BACKUP.exists():
        con.execute(f"copy ftse100_membership to '{BACKUP}' (header, delimiter ',')")
        print(f"\nbacked up current table -> {BACKUP.name}")

    # 1. delete the spurious founding rows whose real episode already exists
    for cn, real, _ in delete_founding:
        con.execute("delete from ftse100_membership where company_number = ? "
                    "and cast(start_date as varchar) = ?", [cn, LAUNCH_PLACEHOLDER])

    # 2. re-date the spurious founding rows that have no real episode
    for cn, real, _ in redate_founding:
        con.execute("update ftse100_membership set start_date = cast(? as date), entry_type = 'added' "
                    "where company_number = ? and cast(start_date as varchar) = ?",
                    [real, cn, LAUNCH_PLACEHOLDER])

    # 3. genuine founding members sit on a placeholder; the index launched 1984-01-03
    moved = con.execute(
        "select count(*) from ftse100_membership where cast(start_date as varchar) = ?", [LAUNCH_PLACEHOLDER]
    ).fetchone()[0]
    con.execute("update ftse100_membership set start_date = cast(? as date) "
                "where cast(start_date as varchar) = ?", [LAUNCH_REAL, LAUNCH_PLACEHOLDER])

    # 4. clear exits the provider record does not support
    for cn, _ in clear_exit:
        con.execute("update ftse100_membership set end_date = null, exit_type = null "
                    "where company_number = ? and end_date is not null "
                    "and end_date = (select max(end_date) from ftse100_membership where company_number = ?)",
                    [cn, cn])

    # 5. every date now traces to the public document
    con.execute("update ftse100_membership set source_url = ? where source_url is null", [PUBLIC_URL])

    print(f"\napplied:")
    print(f"  {len(delete_founding)} spurious founding rows deleted")
    print(f"  {len(redate_founding)} spurious founding rows re-dated to their real entry")
    print(f"  {moved} rows moved {LAUNCH_PLACEHOLDER} -> {LAUNCH_REAL}")
    print(f"  {len(clear_exit)} unsupported exits cleared")
    print(f"  source_url set to the public FTSE Russell document")
    print(f"\n  citation: {CITATION}")
    print(f"  {con.execute('select count(*) from ftse100_membership').fetchone()[0]} rows remain")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
