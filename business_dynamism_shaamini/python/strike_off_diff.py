#!/usr/bin/env python3
"""
strike_off_diff.py — detect company DISSOLUTIONS by diffing two monthly
Companies House "Basic Company Data" snapshots.

Logic: any company number present in the OLD snapshot but ABSENT in the NEW one
left the register in between — i.e. was dissolved (strike-off, or completed
insolvency). This captures ALL exits, including the never-filed shell companies
that the CH-API extraction (which only looks up known dead firms) misses.

Precision: the month/period between the two snapshots. Source: the official CH
monthly bulk product. Run monthly, retaining each snapshot, to build a complete
forward dissolution record.

Usage:
    python3 strike_off_diff.py OLD_snapshot.csv NEW_snapshot.csv 2026-07
    # writes new dissolutions into local business_dynamism.company_dissolutions

Both files are CH "BasicCompanyDataAsOneFile-YYYY-MM-DD.csv" (or any CSV with a
'CompanyNumber' column). Streams the number column only — light on memory.
"""
import csv, sys, psycopg2

def numbers(path):
    s = set()
    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        r = csv.reader(f)
        header = next(r)
        # tolerate quoted/spaced header names
        idx = next(i for i,h in enumerate(header) if h.strip().strip('"')=="CompanyNumber")
        for row in r:
            if row: s.add(row[idx].strip())
    return s

if len(sys.argv) != 4:
    sys.exit("usage: strike_off_diff.py OLD.csv NEW.csv YYYY-MM(period-of-new)")
old_f, new_f, period = sys.argv[1], sys.argv[2], sys.argv[3]

print("reading old snapshot..."); old = numbers(old_f)
print(f"  {len(old):,} companies")
print("reading new snapshot..."); new = numbers(new_f)
print(f"  {len(new):,} companies")
dissolved = old - new
print(f"disappeared between snapshots (dissolved): {len(dissolved):,}")

conn = psycopg2.connect(dbname="business_dynamism", host="/tmp"); conn.autocommit=True
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS company_dissolutions(
    company_number text, dissolved_period text,
    method text DEFAULT 'snapshot_diff', source_url text,
    detected_at timestamptz DEFAULT now(),
    PRIMARY KEY (company_number, dissolved_period))""")
src = "https://download.companieshouse.gov.uk/en_output.html"   # CH bulk product
rows = [(cn, period, 'snapshot_diff', src) for cn in dissolved]
from psycopg2.extras import execute_values
execute_values(cur,
    """INSERT INTO company_dissolutions (company_number,dissolved_period,method,source_url)
       VALUES %s ON CONFLICT DO NOTHING""", rows, page_size=5000)
cur.execute("SELECT count(*) FROM company_dissolutions")
print("company_dissolutions total now:", cur.fetchone()[0])
conn.close()
