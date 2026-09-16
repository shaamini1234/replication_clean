#!/usr/bin/env python3
"""set_ftse_membership_source.py — make the cleared document the sole date source.

ftse100_membership.source_url was doing two jobs at once. On 314 rows it held
the FTSE Russell constituent-history document, which is where the entry and exit
DATES come from. On the other 340 it held a Companies House company URL, which
is evidence of WHO the company is -- not when it joined or left the index. Read
as a single column it looks like the dates have two competing provenances. They
do not.

Now that the FTSE Russell document is cleared for use, it becomes the single
cited source for every membership date, and the Companies House links move to
their own column where they say what they actually mean.

    source_url            the FTSE Russell document, for every row
    identity_source_url   the Companies House record for that company, where one
                          was already held

One honest limit. The document is titled "Historic Additions and Deletions" and
its first event is 19 January 1984, so it contains no addition event for the 125
constituents present when the index launched on 3 January 1984. Their entry date
is the launch itself, which the document implies but does not state. Those rows
carry entry_type='founding' and source_note records that, rather than citing the
document for something it does not say.

Usage:
    python python/set_ftse_membership_source.py --dry-run
    python python/set_ftse_membership_source.py
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import duckdb

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
DOC = ("https://www.lseg.com/content/dam/ftse-russell/en_us/documents/"
       "policy-documents/ftse-100-constituent-history.pdf")
CITE = "FTSE Russell (LSEG), FTSE 100 Historic Additions and Deletions, August 2026"
FOUNDING_NOTE = ("index launch 1984-01-03; the document records additions and deletions "
                 "from 1984-01-19 and contains no addition event for founding constituents")
CHANGE_NOTE = "dated addition/deletion event in the FTSE Russell constituent-history document"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    con = duckdb.connect(DB, read_only=args.dry_run)

    cols = {r[0] for r in con.execute(
        "select column_name from information_schema.columns where table_name='ftse100_membership'").fetchall()}
    n = con.execute("select count(*) from ftse100_membership").fetchone()[0]
    ch = con.execute("select count(*) from ftse100_membership "
                     "where source_url like '%company-information%'").fetchone()[0]
    fnd = con.execute("select count(*) from ftse100_membership where entry_type='founding'").fetchone()[0]
    print(f"ftse100_membership rows            : {n}")
    print(f"  currently citing a CH company URL : {ch}  -> moves to identity_source_url")
    print(f"  founding constituents             : {fnd}  -> source_note explains the launch date")
    print(f"  all rows will cite               : {CITE}")

    if args.dry_run:
        print("\n--dry-run: nothing written"); con.close(); return 0

    for c, t in (("identity_source_url", "VARCHAR"), ("source_note", "VARCHAR"),
                 ("source_citation", "VARCHAR")):
        if c not in cols:
            con.execute(f"alter table ftse100_membership add column {c} {t}")

    # 1. preserve the Companies House links under their real meaning
    con.execute("""update ftse100_membership
                   set identity_source_url = source_url
                   where source_url like '%company-information%'
                     and identity_source_url is null""")
    # 2. the document is now the sole cited source for every membership date
    con.execute("update ftse100_membership set source_url = ?, source_citation = ?", [DOC, CITE])
    # 3. say plainly which rows the document actually evidences
    con.execute("update ftse100_membership set source_note = ? where entry_type = 'founding'",
                [FOUNDING_NOTE])
    con.execute("update ftse100_membership set source_note = ? where entry_type is distinct from 'founding'",
                [CHANGE_NOTE])

    print(f"\n  source_url set to the document on {con.execute('select count(*) from ftse100_membership where source_url = ?', [DOC]).fetchone()[0]} rows")
    print(f"  identity_source_url populated on {con.execute('select count(identity_source_url) from ftse100_membership').fetchone()[0]} rows")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
