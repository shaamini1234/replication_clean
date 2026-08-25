#!/usr/bin/env python3
"""Deep-probe ONE company's latest PDF accounts: is there a text layer, and if so
what do the financial lines actually look like? Reveals scanned-vs-text and why
labels do/don't match."""
import sys, io, time, itertools, requests, re
from pathlib import Path
import pdfplumber

KEYS=[k.strip() for k in (Path.home()/"ch_api_keys.txt").read_text().splitlines() if k.strip()]
kc=itertools.cycle(KEYS)
NUM=sys.argv[1] if len(sys.argv)>1 else "00014504"
def g(u,**q):
    time.sleep(0.5); h=q.pop("_h",{})
    return requests.get(u,params=q or None,auth=(next(kc),""),headers=h,timeout=60)

fh=g(f"https://api.company-information.service.gov.uk/company/{NUM}/filing-history",category="accounts",items_per_page=100)
items=[it for it in fh.json().get("items",[]) if (it.get("links") or {}).get("document_metadata")]
print(f"accounts filings: {len(items)}")
it=items[0]
print("latest:", it.get("date"), "made_up_date=", (it.get("description_values") or {}).get("made_up_date"))
dm=it["links"]["document_metadata"]
meta=g(dm)
print("resources:", list((meta.json().get("resources") or {}).keys()))
pdf=g(dm+"/content", _h={"Accept":"application/pdf"})
print("pdf status/ctype/bytes:", pdf.status_code, pdf.headers.get("content-type"), len(pdf.content), "startsPDF=", pdf.content[:4])
if not pdf.content.startswith(b"%PDF"):
    print("NOT a pdf body:", pdf.content[:200]); sys.exit()
with pdfplumber.open(io.BytesIO(pdf.content)) as doc:
    pages=[(p.extract_text() or "") for p in doc.pages]
chars=sum(len(p) for p in pages)
print(f"pages={len(pages)}  total_text_chars={chars}  -> {'TEXT LAYER' if chars>400 else 'SCANNED (no text)'}")
if chars>400:
    # show any line mentioning key labels
    for kw in ["revenue","turnover","operating profit","before tax","total assets","net assets","staff cost"]:
        hits=[l.strip() for p in pages for l in p.splitlines() if kw in l.lower()][:2]
        print(f"  [{kw}]:")
        for h in hits: print("     ", h[:160])
    print("\n--- first 800 chars of first text-bearing page ---")
    print(next((p for p in pages if len(p)>200),"")[:800])
