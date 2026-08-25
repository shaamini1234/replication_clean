#!/usr/bin/env python3
"""Diagnostic: walk ONE FTSE company through the CH filing->document->parse chain
and print exactly what each step returns, so we can see where 0 comes from."""
import sys, itertools, requests
from pathlib import Path
from lxml import etree

KEYS = [k.strip() for k in (Path.home()/"ch_api_keys.txt").read_text().splitlines() if k.strip()]
key = KEYS[0]
NUM = sys.argv[1] if len(sys.argv) > 1 else "00012901"

def show(label, r):
    ct = r.headers.get("content-type", "") if r is not None else "-"
    print(f"  {label}: status={r.status_code if r else 'ERR'}  ctype={ct}  len={len(r.content) if r else 0}")

# 1. filing history
fh = requests.get(f"https://api.company-information.service.gov.uk/company/{NUM}/filing-history",
                  params={"category": "accounts", "items_per_page": 100}, auth=(key, ""), timeout=40)
print(f"[filing-history] status={fh.status_code}")
items = fh.json().get("items", []) if fh.status_code == 200 else []
print(f"  accounts filings returned: {len(items)}")
if not items:
    print("  -> no accounts filings; company/key issue. First 400 chars:", fh.text[:400]); sys.exit()

# inspect first 3 filings
for it in items[:3]:
    print(f"\n--- filing {it.get('date')} type={it.get('type')} ---")
    links = it.get("links") or {}
    print("  links keys:", list(links.keys()))
    dm = links.get("document_metadata")
    print("  document_metadata:", dm)
    if not dm:
        continue
    # metadata
    meta = requests.get(dm, auth=(key, ""), timeout=40)
    show("metadata GET", meta)
    try:
        print("  metadata.resources:", list((meta.json().get("resources") or {}).keys()))
    except Exception as e:
        print("  metadata parse err:", e)
    # content — try xhtml
    for accept in ("application/xhtml+xml", "application/json", "*/*"):
        c = requests.get(dm + "/content", auth=(key, ""), headers={"Accept": accept}, timeout=40)
        show(f"content GET Accept={accept}", c)
        if c.status_code == 200 and len(c.content) > 500:
            # count ix tags
            try:
                root = etree.fromstring(c.content, etree.XMLParser(recover=True, huge_tree=True))
                nf = [e for e in root.iter() if etree.QName(e).localname == "nonFraction"]
                names = sorted({(e.get("name") or "").split(":")[-1] for e in nf})
                print(f"    ix:nonFraction tags: {len(nf)}; sample names: {names[:25]}")
            except Exception as e:
                print("    parse err:", e, "| first 200 chars:", c.content[:200])
            break
