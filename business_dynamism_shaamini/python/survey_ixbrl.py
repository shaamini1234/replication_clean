#!/usr/bin/env python3
"""Survey the REAL ceiling: for each FTSE company, check the latest accounts
filing and record which document formats CH actually offers (iXBRL vs PDF-only).
Tells us how many firms this route can ever cover before we commit to it."""
import time, itertools, requests, psycopg2
from pathlib import Path

KEYS = [k.strip() for k in (Path.home()/"ch_api_keys.txt").read_text().splitlines() if k.strip()]
keycycle = itertools.cycle(KEYS); PER = 0.55/len(KEYS)
PG = dict(host="ep-nameless-fire-atkh5lxj.c-9.us-east-1.aws.neon.tech", dbname="neondb",
          user="neondb_owner", password="npg_q1uDNWofte0n", sslmode="require", connect_timeout=25)

def get(url, **q):
    time.sleep(PER)
    try:
        return requests.get(url, params=q or None, auth=(next(keycycle), ""), timeout=40)
    except Exception:
        return None

c = psycopg2.connect(**PG); cur = c.cursor()
cur.execute("SELECT DISTINCT company_number FROM ftse100_membership WHERE company_number IS NOT NULL ORDER BY 1")
nums = [r[0] for r in cur.fetchall()]; c.close()
print(f"surveying {len(nums)} FTSE companies (keys: {len(KEYS)})", flush=True)

ixbrl = pdf_only = no_accounts = err = 0
ixbrl_list = []
for i, num in enumerate(nums, 1):
    fh = get(f"https://api.company-information.service.gov.uk/company/{num}/filing-history",
             category="accounts", items_per_page=100)
    if fh is None or fh.status_code != 200:
        err += 1; continue
    items = [it for it in fh.json().get("items", []) if (it.get("links") or {}).get("document_metadata")]
    if not items:
        no_accounts += 1; continue
    # look at up to the 3 most recent accounts filings for an iXBRL resource
    found_ix = False
    for it in items[:3]:
        m = get((it["links"]["document_metadata"]))
        if m is None or m.status_code != 200:
            continue
        res = list((m.json().get("resources") or {}).keys())
        if any("xml" in r or "xhtml" in r for r in res):
            found_ix = True; break
    if found_ix:
        ixbrl += 1; ixbrl_list.append(num)
    else:
        pdf_only += 1
    if i % 25 == 0:
        print(f"  {i}/{len(nums)}  iXBRL={ixbrl} pdf_only={pdf_only} none={no_accounts} err={err}", flush=True)

print("\n===== SURVEY RESULT =====")
print(f"total FTSE companies      : {len(nums)}")
print(f"offer iXBRL (usable)      : {ixbrl}")
print(f"PDF-only (need OCR)       : {pdf_only}")
print(f"no accounts filings       : {no_accounts}")
print(f"errors                    : {err}")
print(f"\nusable share: {100*ixbrl/max(len(nums),1):.0f}%")
Path.home().joinpath("ftse_ixbrl_companies.txt").write_text("\n".join(ixbrl_list))
print(f"iXBRL company numbers written to ~/ftse_ixbrl_companies.txt")
