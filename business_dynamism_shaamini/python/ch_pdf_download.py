#!/usr/bin/env python3
"""
ch_pdf_download.py — download FTSE companies' accounts PDFs from Companies House
into a folder, with a manifest, ready for offline OCR.

Keys: ~/ch_api_keys.txt (one per line). Runs on your machine/server.

Downloads, per company, the 'accounts' (type AA) filings' PDFs and records a row
in manifest.csv: company_number, company_name, period_end, filing_date, pages_hint,
bytes, source_url, path. Nothing is parsed here — just fetched + catalogued.

Scope (keep it tractable — start small, expand):
  --from-year 2011      only filings made up to >= this year (default 2011)
  --companies current   'current' (has a ticker, ~97) | 'all' (328)   default current
  --limit N             first N companies only (pilot)
  --outdir ch_pdfs      where PDFs go (default ./ch_pdfs)

Example pilot:
  python3 python/ch_pdf_download.py --limit 3 --from-year 2015
Full current constituents:
  python3 python/ch_pdf_download.py --companies current --from-year 2011
"""
import os, sys, csv, time, itertools, requests, duckdb
from pathlib import Path

KEYS = [k.strip() for k in (Path.home()/"ch_api_keys.txt").read_text().splitlines() if k.strip()]
if not KEYS: sys.exit("no keys in ~/ch_api_keys.txt")
kc = itertools.cycle(KEYS); PER = 0.55/len(KEYS)
A = sys.argv
def av(f, d): return A[A.index(f)+1] if f in A else d
FROM_YEAR = int(av("--from-year", "2011"))
SCOPE     = av("--companies", "current")
LIMIT     = int(av("--limit", "0")) or None
OUTDIR    = Path(av("--outdir", "ch_pdfs")); OUTDIR.mkdir(exist_ok=True)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB   = os.path.join(HERE, "business_dynamism_v1_20260820.duckdb")

def get(url, **q):
    time.sleep(PER)
    for _ in range(len(KEYS)):
        try:
            r = requests.get(url, params=q or None, auth=(next(kc), ""), timeout=90,
                             headers=q.pop("_h", None) or {})
        except Exception:
            continue
        if r.status_code == 429: time.sleep(5); continue
        if r.status_code in (401,403): continue
        return r
    return None

# universe from the DB
con = duckdb.connect(DB, read_only=True)
if SCOPE == "current":
    rows = con.execute("""SELECT m.company_number, MIN(m.company_name) AS company_name
        FROM ftse100_membership m JOIN ftse100_mapping g ON m.company_number=g.company_number
        WHERE g.ticker IS NOT NULL GROUP BY m.company_number ORDER BY 1""").fetchdf()
else:
    rows = con.execute("SELECT company_number, MIN(company_name) AS company_name FROM ftse100_membership "
                       "WHERE company_number IS NOT NULL GROUP BY company_number ORDER BY 1").fetchdf()
con.close()
comps = list(rows.itertuples(index=False))
if LIMIT: comps = comps[:LIMIT]
print(f"companies: {len(comps)}  from_year>={FROM_YEAR}  outdir={OUTDIR}", flush=True)

man_path = OUTDIR/"manifest.csv"
new = not man_path.exists()
mf = open(man_path, "a", newline="")
w = csv.writer(mf)
if new: w.writerow(["company_number","company_name","period_end","filing_date","bytes","source_url","path"])

n_files = 0
for i,(num,name) in enumerate(comps,1):
    fh = get(f"https://api.company-information.service.gov.uk/company/{num}/filing-history",
             category="accounts", items_per_page=100)
    items = fh.json().get("items", []) if fh and fh.status_code==200 else []
    got = 0
    for it in items:
        if it.get("type") not in ("AA","AAMD","group"):
            pass  # keep all accounts-category items
        pend = ((it.get("description_values") or {}).get("made_up_date")) or it.get("action_date") or it.get("date")
        yr = int(str(pend)[:4]) if pend and str(pend)[:4].isdigit() else 0
        if yr < FROM_YEAR: continue
        dm = (it.get("links") or {}).get("document_metadata")
        if not dm: continue
        content_url = dm + "/content"
        fn = OUTDIR/f"{num}_{pend}.pdf"
        if fn.exists() and fn.stat().st_size > 1000:
            continue  # already have it
        doc = get(content_url, _h={"Accept":"application/pdf"})
        if doc is None or doc.status_code!=200 or not doc.content.startswith(b"%PDF"):
            continue
        fn.write_bytes(doc.content)
        w.writerow([num, name, pend, it.get("date"), len(doc.content), content_url, str(fn)])
        mf.flush(); got += 1; n_files += 1
    print(f"[{i}/{len(comps)}] {num} {name[:30]:30s} +{got} pdfs (total {n_files})", flush=True)

mf.close()
print(f"\nDONE. {n_files} PDFs in {OUTDIR}. Manifest: {man_path}")
print("This folder is what the OCR extractor reads next.")
