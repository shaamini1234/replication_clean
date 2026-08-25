#!/usr/bin/env python3
"""
ch_pdf_ocr_extract.py — read the downloaded CH accounts PDFs and pull the headline
figures, WITH EVIDENCE. Reads a folder (default ./ch_pdfs) + its manifest.csv.

Strategy (keeps OCR cheap on 300-page scans):
  1. Try the text layer first (pdfplumber). Most CH FTSE filings are scanned, so
     usually empty -> step 2.
  2. LOCATE pass: OCR each page at LOW dpi, keep only pages whose text contains a
     statement anchor ("consolidated income statement", "...financial position",
     "consolidated balance sheet", "group income statement", etc.).
  3. READ pass: re-OCR just those candidate pages at HIGH dpi; extract each metric
     from the line carrying its label (first monetary number = current-year column);
     apply £m / £'000 scale from the statement header.

Every value stored keeps: evidence line, page, scale, method (text|ocr), confidence,
source_url (from manifest), and a sanity flag. Nothing invented; misses stay blank.
Resumable: skips (company_number, period_end) already in the output CSV.

Deps:  pip install pdfplumber pytesseract pdf2image
       (system) tesseract + poppler   [mac: brew install tesseract poppler]

Run:   python3 python/ch_pdf_ocr_extract.py --dir ch_pdfs --limit 5   # pilot
       python3 python/ch_pdf_ocr_extract.py --dir ch_pdfs             # full
"""
import os, re, sys, csv, glob
from pathlib import Path

A=sys.argv
def av(f,d): return A[A.index(f)+1] if f in A else d
DIR   = Path(av("--dir","ch_pdfs"))
LIMIT = int(av("--limit","0")) or None
LO_DPI= int(av("--lo-dpi","110"))
HI_DPI= int(av("--hi-dpi","300"))
MAXP  = int(av("--max-pages","0")) or None   # cap locate pass if set
OUT   = DIR/"ch_ocr_extract_review.csv"

import pdfplumber
try:
    import pytesseract
    from pdf2image import convert_from_path
    HAVE_OCR=True
except Exception:
    HAVE_OCR=False

ANCHORS = [re.compile(a) for a in [
    r"consolidated income statement", r"consolidated statement of profit",
    r"consolidated statement of comprehensive income",
    r"consolidated statement of financial position", r"consolidated balance sheet",
    r"group income statement", r"group balance sheet",
    r"statement of financial position", r"income statement"]]
METRICS = [
 # revenue synonyms incl. "sales" (Metlen) and "total income" (banks e.g. Barclays)
 ("revenue",          re.compile(r"\b(revenue|turnover|group revenue|total revenue|net sales|sales|total income)\b", re.I)),
 ("operating_profit", re.compile(r"\boperating (profit|loss)", re.I)),
 ("pretax_profit",    re.compile(r"profit .*before tax|(loss|profit) before (income )?tax", re.I)),
 # profit for the year / after tax / after income tax
 ("profit_loss",      re.compile(r"\b(profit|loss) (for the|after)\b", re.I)),
 ("total_assets",     re.compile(r"\btotal assets\b", re.I)),
 ("net_assets",       re.compile(r"\bnet assets\b|total equity\b", re.I)),
 ("staff_costs",      re.compile(r"staff costs|wages and salaries|employee benefit", re.I)),
 ("depreciation",     re.compile(r"\bdepreciation\b", re.I)),
]
NUM = re.compile(r"\(?-?[£$€]?\s?\d[\d,]{2,}(?:\.\d+)?\)?")
# don't let "cost of sales"/"cost of goods sold" masquerade as revenue
REV_GUARD = re.compile(r"cost of (sales|goods)", re.I)

def currency_of(txt):
    l = txt[:1200].lower()
    if re.search(r"€|eur\b|euro", l):    return "EUR"
    if re.search(r"\$|usd\b|dollar", l): return "USD"
    if re.search(r"£|gbp\b|sterling|pound", l): return "GBP"
    return ""

def amount(tok):
    neg="(" in tok; t=re.sub(r"[^\d.]","",tok)
    if t in ("","."): return None
    try: v=float(t)
    except: return None
    return -v if neg else v

def scale_of(txt):
    l=txt.lower()
    if re.search(r"£\s?m\b|in millions|\$m\b|€m\b|£ million", l): return 1_000_000,"millions"
    if re.search(r"£?\s?'?000|thousand", l): return 1_000,"thousands"
    return 1,"units"

def extract_page(txt):
    out={}
    sm,sn=scale_of(txt[:800])
    ccy=currency_of(txt)
    for line in txt.splitlines():
        for metric,pat in METRICS:
            if metric in out: continue
            if not pat.search(line): continue
            if metric=="revenue" and REV_GUARD.search(line): continue  # skip cost of sales/goods
            nums=NUM.findall(line)
            if not nums: continue
            v=amount(nums[0])
            if v is None: continue
            out[metric]=(v*sm, sn, ccy, line.strip()[:180])
    return out

def page_texts(path):
    """Yield (page_no, text, method) — text layer if present else '' placeholder."""
    with pdfplumber.open(path) as pdf:
        n=len(pdf.pages)
        for i,p in enumerate(pdf.pages,1):
            yield i,(p.extract_text() or ""),n

def main():
    if not DIR.exists(): sys.exit(f"no folder {DIR}")
    man={}
    mp=DIR/"manifest.csv"
    if mp.exists():
        for r in csv.DictReader(open(mp)):
            man[(r["company_number"], r["period_end"])]=r["source_url"]
    done=set()
    if OUT.exists():
        for r in csv.DictReader(open(OUT)):
            done.add((r["company_number"], r["period_end"]))
    w_new = not OUT.exists()
    out=open(OUT,"a",newline=""); w=csv.writer(out)
    if w_new: w.writerow(["company_number","period_end","metric","value","scale","currency","method",
                          "confidence","page","evidence","sanity_flag","source_url"])

    pdfs=sorted(glob.glob(str(DIR/"*.pdf")))
    if LIMIT: pdfs=pdfs[:LIMIT]
    print(f"pdfs: {len(pdfs)}  OCR available: {HAVE_OCR}", flush=True)

    for pi,path in enumerate(pdfs,1):
        base=os.path.basename(path)[:-4]
        m=re.match(r"([A-Z0-9]+)_(\d{4}-\d{2}-\d{2})$", base)
        cn, pend = (m.group(1), m.group(2)) if m else (base, "")
        if (cn,pend) in done:
            print(f"[{pi}/{len(pdfs)}] {base} (skip, done)"); continue
        src=man.get((cn,pend),"")
        # 1) text layer
        cand=[]  # (page_no, text, method)
        has_text=False
        for pno,txt,npages in page_texts(path):
            if MAXP and pno>MAXP: break
            if len(txt)>200:
                has_text=True
                if any(a.search(txt.lower()) for a in ANCHORS):
                    cand.append((pno,txt,"text"))
        # 2) OCR locate + read if no text layer
        if not has_text:
            if not HAVE_OCR:
                w.writerow([cn,pend,"","","","scanned","need_ocr","","","no_ocr_installed",src]); out.flush()
                print(f"[{pi}/{len(pdfs)}] {base} scanned, OCR not installed"); continue
            imgs=convert_from_path(path, dpi=LO_DPI)
            if MAXP: imgs=imgs[:MAXP]
            locate=[]
            for idx,im in enumerate(imgs,1):
                t=pytesseract.image_to_string(im)
                if any(a.search(t.lower()) for a in ANCHORS):
                    locate.append(idx)
            for idx in locate:
                hi=convert_from_path(path, dpi=HI_DPI, first_page=idx, last_page=idx)
                if hi: cand.append((idx, pytesseract.image_to_string(hi[0]), "ocr"))
        # 3) extract from candidate pages
        found={}
        for pno,txt,method in cand:
            for metric,(val,sn,ccy,ev) in extract_page(txt).items():
                if metric not in found:
                    found[metric]=(val,sn,ccy,method,pno,ev)
        # sanity + write
        rev=found.get("revenue",(None,))[0]; ta=found.get("total_assets",(None,))[0]
        for metric,(val,sn,ccy,method,pno,ev) in found.items():
            flag=""
            if metric=="total_assets" and rev and ta and ta<rev*0.05: flag="assets<<revenue?"
            conf="high" if method=="text" else "ocr_review"
            w.writerow([cn,pend,metric,val,sn,ccy,method,conf,pno,ev,flag,src])
        out.flush()
        print(f"[{pi}/{len(pdfs)}] {base}  {len(found)} metrics  ({'text' if has_text else 'ocr'})", flush=True)

    out.close()
    print(f"\nDONE -> {OUT}. Spot-check: each value has evidence + page + source_url.")

if __name__=="__main__":
    main()
