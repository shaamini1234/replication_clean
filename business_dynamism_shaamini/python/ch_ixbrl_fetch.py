#!/usr/bin/env python3
"""
ch_ixbrl_fetch.py — download & parse FULL (iXBRL) accounts from Companies House
for the FTSE universe: the large-firm financials the CH *bulk* product omits.

Every value is a sourced fact. Each account year is stamped with source_url =
the official CH document-content URL it was parsed from. Nothing is estimated.

Flow per company:
  filing-history?category=accounts  ->  each filing's document_metadata
  ->  GET .../content  (Accept: application/xhtml+xml)  ->  parse ix:nonFraction

Writes Neon table  ch_ixbrl_accounts  (PK company_number, period_end).

Keys: ~/ch_api_keys.txt (one per line) — same file the profile extractor uses.

Run (validate on 3 first, then full):
  pip install requests lxml psycopg2-binary
  python3 ch_ixbrl_fetch.py --limit 3
  nohup python3 ch_ixbrl_fetch.py > ~/ixbrl.log 2>&1 &     # full, unattended
  tail -f ~/ixbrl.log
"""
import sys, time, itertools, requests, psycopg2, psycopg2.extras
from pathlib import Path
from lxml import etree
from _neon import PASSWORD as _NEON_PASSWORD

KEYS = [k.strip() for k in (Path.home()/"ch_api_keys.txt").read_text().splitlines() if k.strip()]
if not KEYS:
    sys.exit("no keys in ~/ch_api_keys.txt")
keycycle = itertools.cycle(KEYS)
PER_REQ = 0.55 / len(KEYS)          # keep each key under 600 req / 5 min

FH   = "https://api.company-information.service.gov.uk/company/{}/filing-history"
PG = dict(host="ep-nameless-fire-atkh5lxj.c-9.us-east-1.aws.neon.tech", dbname="neondb",
          user="neondb_owner", password=_NEON_PASSWORD, sslmode="require", connect_timeout=25)

LIMIT = None
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit")+1])

# concept local-name (lowercased, prefix stripped) -> our column
CONCEPTS = {
 "revenue":          {"turnover","turnoverrevenue","revenue","turnovergrossoperatingrevenue"},
 "operating_profit": {"operatingprofitloss"},
 "profit_loss":      {"profitloss","profitlossforperiod"},
 "pretax_profit":    {"profitlossonordinaryactivitiesbeforetax","profitlossbeforetax"},
 "total_assets":     {"assets","totalassets"},
 "net_assets":       {"netassetsliabilities","equity","totalequity","shareholdersfunds"},
 "staff_costs":      {"staffcosts","staffcostsemployeebenefitsexpense","wagesandsalaries"},
 "depreciation":     {"depreciationofpropertyplantandequipment","depreciationexpense",
                      "depreciationamortisationexpense","depreciationamortisationimpairmentexpense"},
 "employees":        {"averagenumberemployeesduringperiod","averagenumberofemployees"},
}
LOOKUP = {v: col for col, s in CONCEPTS.items() for v in s}

def req(url, accept=None):
    """GET with key rotation + pacing. Returns requests.Response or None."""
    for _ in range(len(KEYS)):
        key = next(keycycle)
        time.sleep(PER_REQ)
        h = {"Accept": accept} if accept else {}
        try:
            r = requests.get(url, auth=(key, ""), headers=h, timeout=40)
        except Exception:
            continue
        if r.status_code == 429:
            time.sleep(5); continue
        if r.status_code in (401, 403):
            continue
        return r
    return None

def parse_num(el):
    t = (el.text or "").strip().replace(",", "")
    if t in ("", "-"):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    scale = el.get("scale")
    if scale:
        v *= 10 ** int(scale)
    if el.get("sign") == "-":
        v = -v
    return v

def parse_ixbrl(content):
    """Return {period_end: {col: value}} for each reporting context found."""
    try:
        root = etree.fromstring(content, etree.XMLParser(recover=True, huge_tree=True))
    except Exception:
        return {}
    if root is None:
        return {}
    # contextRef -> period end date (use endDate for durations, instant for balances)
    ctx_end = {}
    for c in root.iter():
        if etree.QName(c).localname != "context":
            continue
        cid = c.get("id")
        end = None
        for d in c.iter():
            ln = etree.QName(d).localname
            if ln in ("endDate", "instant") and d.text:
                end = d.text.strip()
        # skip contexts with explicit segment/scenario dimensions (want consolidated whole-entity)
        has_dim = any(etree.QName(x).localname in ("segment", "scenario") for x in c.iter())
        if cid and end and not has_dim:
            ctx_end[cid] = end
    out = {}
    for el in root.iter():
        if etree.QName(el).localname != "nonFraction":
            continue
        name = el.get("name") or ""
        local = name.split(":")[-1].lower()
        col = LOOKUP.get(local)
        if not col:
            continue
        cref = el.get("contextRef")
        end = ctx_end.get(cref)
        if not end:
            continue
        val = parse_num(el)
        if val is None:
            continue
        rec = out.setdefault(end, {})
        # first non-dimensional value wins per period (consolidated primary statement)
        rec.setdefault(col, val)
    return out

def main():
    c = psycopg2.connect(**PG); c.autocommit = True; cur = c.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ch_ixbrl_accounts(
          company_number text, period_end date,
          revenue numeric, operating_profit numeric, profit_loss numeric,
          pretax_profit numeric, total_assets numeric, net_assets numeric,
          staff_costs numeric, depreciation numeric, employees numeric,
          source_url text, filing_date date, fetched_at timestamptz default now(),
          PRIMARY KEY (company_number, period_end))""")
    cur.execute("SELECT DISTINCT company_number FROM ftse100_membership "
                "WHERE company_number IS NOT NULL ORDER BY company_number")
    companies = [r[0] for r in cur.fetchall()]
    if LIMIT:
        companies = companies[:LIMIT]
    print(f"companies to process: {len(companies)}  (keys: {len(KEYS)})", flush=True)

    tot_rows = 0
    for i, num in enumerate(companies, 1):
        r = req(FH.format(num) + "?category=accounts&items_per_page=100")
        if r is None or r.status_code != 200:
            print(f"[{i}/{len(companies)}] {num}  filing-history {r.status_code if r else 'ERR'}", flush=True)
            continue
        items = r.json().get("items", [])
        got = 0
        for it in items[:30]:
            dm = (it.get("links") or {}).get("document_metadata")
            if not dm:
                continue
            content_url = dm + "/content"
            doc = req(content_url, accept="application/xhtml+xml")
            if doc is None or doc.status_code != 200:
                continue
            if "xml" not in doc.headers.get("content-type", "") and "html" not in doc.headers.get("content-type", ""):
                continue  # PDF-only (older) filing — no iXBRL to parse
            periods = parse_ixbrl(doc.content)
            fdate = it.get("date")
            for pend, rec in periods.items():
                if not rec:
                    continue
                cur.execute("""
                    INSERT INTO ch_ixbrl_accounts
                      (company_number,period_end,revenue,operating_profit,profit_loss,
                       pretax_profit,total_assets,net_assets,staff_costs,depreciation,
                       employees,source_url,filing_date)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (company_number,period_end) DO UPDATE SET
                      revenue=coalesce(ch_ixbrl_accounts.revenue,EXCLUDED.revenue),
                      operating_profit=coalesce(ch_ixbrl_accounts.operating_profit,EXCLUDED.operating_profit),
                      profit_loss=coalesce(ch_ixbrl_accounts.profit_loss,EXCLUDED.profit_loss),
                      pretax_profit=coalesce(ch_ixbrl_accounts.pretax_profit,EXCLUDED.pretax_profit),
                      total_assets=coalesce(ch_ixbrl_accounts.total_assets,EXCLUDED.total_assets),
                      net_assets=coalesce(ch_ixbrl_accounts.net_assets,EXCLUDED.net_assets),
                      staff_costs=coalesce(ch_ixbrl_accounts.staff_costs,EXCLUDED.staff_costs),
                      depreciation=coalesce(ch_ixbrl_accounts.depreciation,EXCLUDED.depreciation),
                      employees=coalesce(ch_ixbrl_accounts.employees,EXCLUDED.employees),
                      source_url=coalesce(ch_ixbrl_accounts.source_url,EXCLUDED.source_url)
                """, (num, pend, rec.get("revenue"), rec.get("operating_profit"),
                      rec.get("profit_loss"), rec.get("pretax_profit"), rec.get("total_assets"),
                      rec.get("net_assets"), rec.get("staff_costs"), rec.get("depreciation"),
                      rec.get("employees"), content_url, fdate))
                got += 1; tot_rows += 1
        print(f"[{i}/{len(companies)}] {num}  {got} account-years", flush=True)
    print(f"DONE. account-years written/updated: {tot_rows}", flush=True)
    c.close()

if __name__ == "__main__":
    main()
