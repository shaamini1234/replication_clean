#!/usr/bin/env python3
"""
ch_pdf_reader.py — read FULL statutory accounts filed as PDF at Companies House
for the FTSE universe, and extract the headline financials WITH EVIDENCE.

Why this exists: most large listed groups file PDF accounts at CH, not tagged
iXBRL. The free bulk product omits them; the iXBRL route can't parse them.

HONESTY RULES (this project's whole point):
  * Nothing is invented. A figure is stored only if it was found on a line that
    carries its label. If a metric isn't found, it stays NULL.
  * Every stored figure keeps: the exact text line it came from (evidence),
    the page number, the scale that was applied, the extraction method, and the
    official CH document URL. So any number can be checked against the source.
  * method = 'pdf_text'  (real text layer, high confidence)
            | 'pdf_ocr'   (scanned image, OCR'd, LOWER confidence — verify)
    Store this so PDF figures are filterable and never confused with iXBRL facts.

Two passes:
  text layer  -> pdfplumber (fast, accurate)
  scanned     -> only if --ocr AND tesseract+poppler installed; else recorded as
                 'scanned_no_ocr' so we know exactly which firms still need work.

Writes Neon table  ch_pdf_accounts  and a review CSV in ./output for spot-checking.

Deps:
  pip install requests pdfplumber psycopg2-binary
  # OCR (optional): brew install tesseract poppler ; pip install pytesseract pdf2image

Run:
  python3 python/ch_pdf_reader.py --limit 3            # validate on 3 firms
  python3 python/ch_pdf_reader.py --years 4            # 4 most recent yrs each
  python3 python/ch_pdf_reader.py                      # full FTSE universe
  python3 python/ch_pdf_reader.py --ocr                # also OCR scanned ones
"""
import sys, os, re, io, time, csv, itertools, requests, psycopg2
from pathlib import Path
from _neon import PASSWORD as _NEON_PASSWORD

# ---------------- config ----------------
KEYS = [k.strip() for k in (Path.home()/"ch_api_keys.txt").read_text().splitlines() if k.strip()]
if not KEYS:
    sys.exit("no keys in ~/ch_api_keys.txt")
keycycle = itertools.cycle(KEYS); PER = 0.55/len(KEYS)
PG = dict(host="ep-nameless-fire-atkh5lxj.c-9.us-east-1.aws.neon.tech", dbname="neondb",
          user="neondb_owner", password=_NEON_PASSWORD, sslmode="require", connect_timeout=25)
ARG = sys.argv
def argval(flag, default):
    return ARG[ARG.index(flag)+1] if flag in ARG else default
LIMIT = int(argval("--limit", 0)) or None
YEARS = int(argval("--years", 4))
DO_OCR = "--ocr" in ARG
OUTDIR = Path(__file__).resolve().parent.parent / "output"; OUTDIR.mkdir(exist_ok=True)

try:
    import pdfplumber
except ImportError:
    sys.exit("pip install pdfplumber")

# ---------------- metric labels ----------------
# ordered: more specific first so 'profit before tax' isn't caught by 'profit'
METRICS = [
 ("revenue",          re.compile(r"\b(revenue|turnover)\b", re.I)),
 ("operating_profit", re.compile(r"\boperating (profit|loss|profit/\(loss\))", re.I)),
 ("pretax_profit",    re.compile(r"\bprofit\b.*before tax|loss before tax|before taxation", re.I)),
 ("profit_loss",      re.compile(r"\bprofit (for|attributable).*(year|period)|profit for the", re.I)),
 ("total_assets",     re.compile(r"\btotal assets\b", re.I)),
 ("net_assets",       re.compile(r"\bnet assets\b|total equity\b", re.I)),
 ("staff_costs",      re.compile(r"\bstaff costs\b|wages and salaries|employee benefit", re.I)),
 ("depreciation",     re.compile(r"\bdepreciation\b", re.I)),
 ("employees",        re.compile(r"average.*number.*employ", re.I)),
]
NUM = re.compile(r"\(?-?[£$]?\s?\d[\d,]{2,}(?:\.\d+)?\)?")   # >=1,000-ish or parenthesised

def parse_amount(tok):
    neg = "(" in tok
    t = re.sub(r"[^\d.]", "", tok)
    if t in ("", "."):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v

def scale_for(text):
    """Detect reporting scale from statement header text."""
    low = text.lower()
    if re.search(r"£?\s?m(illion)?\b|in millions|£m\b", low): return 1_000_000, "millions"
    if re.search(r"£?\s?'?000|thousand", low):                return 1_000, "thousands"
    return 1, "units"

# ---------------- CH fetch ----------------
def get(url, **q):
    time.sleep(PER)
    for _ in range(len(KEYS)):
        try:
            r = requests.get(url, params=q or None, auth=(next(keycycle), ""),
                             timeout=60, headers=q.pop("_h", None) or {})
        except Exception:
            continue
        if r.status_code == 429:
            time.sleep(5); continue
        if r.status_code in (401, 403):
            continue
        return r
    return None

def download_pdf(doc_meta_url):
    r = get(doc_meta_url + "/content", _h={"Accept": "application/pdf"})
    if r is None or r.status_code != 200 or not r.content.startswith(b"%PDF"):
        return None
    return r.content

# ---------------- extraction ----------------
def extract_from_pages(pages):
    """pages: list[str]. Return dict metric -> (value_raw, scale_mult, scale_name, evidence, page_no)."""
    found = {}
    for pno, ptext in enumerate(pages, 1):
        if not ptext:
            continue
        smult, sname = scale_for(ptext[:600])   # scale usually stated near statement head
        for line in ptext.splitlines():
            for metric, pat in METRICS:
                if metric in found:
                    continue
                if not pat.search(line):
                    continue
                nums = NUM.findall(line)
                if not nums:
                    continue
                # first number after the label text = current-year column
                val = parse_amount(nums[0])
                if val is None:
                    continue
                if metric == "employees":       # headcount is not scaled
                    smult, sname = 1, "units"
                found[metric] = (val, smult, sname, line.strip()[:180], pno)
    return found

def read_pdf(content):
    """Return (method, pages_text_list). method in pdf_text|scanned."""
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages[:60]]
    chars = sum(len(p) for p in pages)
    if chars > 400:                       # real text layer
        return "pdf_text", pages
    return "scanned", pages               # image-only

def ocr_pdf(content):
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError:
        return None
    imgs = convert_from_bytes(content, dpi=200, first_page=1, last_page=40)
    return [pytesseract.image_to_string(im) for im in imgs]

# ---------------- main ----------------
def main():
    c = psycopg2.connect(**PG); c.autocommit = True; cur = c.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS ch_pdf_accounts(
        company_number text, period_end date, metric text,
        value numeric, scale_name text, method text,
        evidence text, page_no int, source_url text, filing_date date,
        fetched_at timestamptz default now(),
        PRIMARY KEY (company_number, period_end, metric))""")
    cur.execute("SELECT DISTINCT company_number FROM ftse100_membership "
                "WHERE company_number IS NOT NULL ORDER BY 1")
    nums = [r[0] for r in cur.fetchall()]
    if LIMIT:
        nums = nums[:LIMIT]
    print(f"companies: {len(nums)}  years/each: {YEARS}  ocr: {DO_OCR}  keys: {len(KEYS)}", flush=True)

    review = open(OUTDIR/"pdf_extract_review.csv", "w", newline="")
    w = csv.writer(review)
    w.writerow(["company_number","period_end","metric","value","scale","method","page","evidence","source_url"])

    stats = {"pdf_text":0, "pdf_ocr":0, "scanned_no_ocr":0, "no_pdf":0}
    total_vals = 0
    for i, num in enumerate(nums, 1):
        fh = get(f"https://api.company-information.service.gov.uk/company/{num}/filing-history",
                 category="accounts", items_per_page=100)
        items = [it for it in (fh.json().get("items", []) if fh and fh.status_code==200 else [])
                 if (it.get("links") or {}).get("document_metadata")]
        if not items:
            stats["no_pdf"] += 1
            print(f"[{i}/{len(nums)}] {num}  no accounts docs", flush=True); continue
        yr_done = 0
        for it in items:
            if yr_done >= YEARS:
                break
            pend = ((it.get("description_values") or {}).get("made_up_date")) or it.get("action_date")
            if not pend:
                continue
            content = download_pdf(it["links"]["document_metadata"])
            if not content:
                continue
            src = it["links"]["document_metadata"] + "/content"
            method, pages = read_pdf(content)
            if method == "scanned":
                if DO_OCR:
                    ocrpages = ocr_pdf(content)
                    if ocrpages is None:
                        stats["scanned_no_ocr"] += 1; continue
                    pages, method = ocrpages, "pdf_ocr"
                else:
                    stats["scanned_no_ocr"] += 1; continue
            found = extract_from_pages(pages)
            if not found:
                continue
            stats["pdf_text" if method=="pdf_text" else "pdf_ocr"] += 1
            yr_done += 1
            for metric, (val, smult, sname, ev, pno) in found.items():
                scaled = val * smult
                cur.execute("""INSERT INTO ch_pdf_accounts
                  (company_number,period_end,metric,value,scale_name,method,evidence,page_no,source_url,filing_date)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT (company_number,period_end,metric) DO UPDATE SET
                    value=EXCLUDED.value, scale_name=EXCLUDED.scale_name, method=EXCLUDED.method,
                    evidence=EXCLUDED.evidence, page_no=EXCLUDED.page_no, source_url=EXCLUDED.source_url""",
                  (num, pend, metric, scaled, sname, method, ev, pno, src, it.get("date")))
                w.writerow([num, pend, metric, scaled, sname, method, pno, ev, src]); total_vals += 1
        print(f"[{i}/{len(nums)}] {num}  {yr_done} yrs parsed", flush=True)

    review.close(); c.close()
    print("\n===== SUMMARY =====")
    for k, v in stats.items():
        print(f"  {k:16s}: {v}")
    print(f"  values written  : {total_vals}")
    print(f"  review CSV      : {OUTDIR/'pdf_extract_review.csv'}")
    print("\nSpot-check the review CSV: every 'value' has its evidence line + source_url.")

if __name__ == "__main__":
    main()
