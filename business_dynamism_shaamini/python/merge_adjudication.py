#!/usr/bin/env python3
"""Fold the source-based adjudication of the amber bucket into the entrant analysis.
Produces final_class + is_genuinely_new + source URL on each entrant, a coarse-bucket
summary, and regenerates entrant_analysis.html mapped over time."""
import os, json, pandas as pd, numpy as np
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
adj=pd.read_csv(os.path.join(HERE,"adjudication_results.csv"), sep="|")
adj["entry_year"]=pd.to_numeric(adj["entry_year"],errors="coerce")
akey=adj.set_index(["company_name","entry_year"])

def apply_adj(df):
    df=df.copy(); df["entry_year"]=pd.to_numeric(df["entry_year"],errors="coerce")
    def look(r,c):
        try: return akey.at[(r["company_name"],r["entry_year"]),c]
        except: return np.nan
    df["adjudicated_class"]=df.apply(lambda r: look(r,"adjudicated_class"),axis=1)
    df["adjudication_source_url"]=df.apply(lambda r: look(r,"source_url"),axis=1)
    df["final_class"]=np.where(df["adjudicated_class"].notna(),df["adjudicated_class"],df["provisional_class"])
    return df

CORP={"spin_off","merger","demutualisation_ipo","reincorporation_redomicile",
      "reincorporation_rename","ipo_established","wrapper_reincorp","new_entity_renamed","spac_shell"}
def coarse(fc):
    if fc=="genuinely_new": return "genuinely_new_verified"
    if fc=="genuinely_new_provisional": return "genuinely_new_provisional"
    if fc in CORP: return "corporate_action"
    if fc in ("established","established_organic_riser"): return "established"
    if fc=="re_entry": return "re_entry"
    if fc=="historical_unmatched": return "historical_no_ch_number"
    if fc=="unknown_age": return "unknown_age"
    if fc=="founding_member": return "founding_member"
    return fc

f=apply_adj(pd.read_csv(os.path.join(HERE,"ftse_entrants_classified.csv")))
s=apply_adj(pd.read_csv(os.path.join(HERE,"sp500_entrants_classified.csv")))
# S&P also adjudicated by TICKER (historical names are blank) — apply where still provisional
tk=os.path.join(HERE,"adjudication_by_ticker.csv")
if os.path.exists(tk):
    t=pd.read_csv(tk,sep="|"); t["entry_year"]=pd.to_numeric(t["entry_year"],errors="coerce")
    tkey=t.set_index(["id" if "id" in t else "ticker"]) if False else t.set_index("ticker")
    def tlook(r,c):
        try: return tkey.at[r["id"],c]
        except: return np.nan
    for i,r in s.iterrows():
        if pd.isna(r.get("adjudicated_class")):
            ac=tlook(r,"adjudicated_class")
            if pd.notna(ac):
                s.at[i,"adjudicated_class"]=ac
                s.at[i,"adjudication_source_url"]=tlook(r,"source_url")
                s.at[i,"final_class"]=ac
for df,name in [(f,"ftse_entrants_classified.csv"),(s,"sp500_entrants_classified.csv")]:
    df["coarse_class"]=df["final_class"].map(coarse)
    df.to_csv(os.path.join(HERE,name),index=False)

def summary(df,idx):
    d=df.copy(); d["index"]=idx
    return d.groupby(["index","coarse_class"]).size().rename("n").reset_index()
summ=pd.concat([summary(f,"FTSE100"),summary(s,"S&P500")],ignore_index=True)
summ.to_csv(os.path.join(HERE,"entrant_final_summary.csv"),index=False)

print("=== FINAL coarse composition ===")
print(summ.pivot(index="coarse_class",columns="index",values="n").fillna(0).astype(int).to_string())

# among genuinely-classifiable arrivals (exclude founding_member/unknown/historical), the headline
def headline(df,idx):
    ok=df[~df["coarse_class"].isin(["founding_member","unknown_age","historical_no_ch_number"])]
    n=len(ok); gv=(ok.coarse_class=="genuinely_new_verified").sum()
    gp=(ok.coarse_class=="genuinely_new_provisional").sum(); ca=(ok.coarse_class=="corporate_action").sum()
    print(f"\n{idx}: classifiable arrivals={n} | corporate_action={ca} "
          f"| genuinely_new_verified={gv} | genuinely_new_provisional(unverified)={gp} | re_entry={(ok.coarse_class=='re_entry').sum()} | established={(ok.coarse_class=='established').sum()}")
headline(f,"FTSE100"); headline(s,"S&P500")

# ---- regenerate chart over time (coarse buckets) ----
CB=["genuinely_new_verified","genuinely_new_provisional","corporate_action","re_entry",
    "established","historical_no_ch_number","unknown_age"]
LAB={"genuinely_new_verified":"Genuinely new (source-verified)","genuinely_new_provisional":"Genuinely new (provisional, unverified)",
     "corporate_action":"Corporate action (spin-off / merger / reincorp / demutualisation)","re_entry":"Re-entry (was in before)",
     "established":"Established business","historical_no_ch_number":"Historical — no reliable CH number","unknown_age":"Unknown age (data gap)"}
COL={"genuinely_new_verified":"#2e8b57","genuinely_new_provisional":"#8fbf9f","corporate_action":"#c0562e",
     "re_entry":"#6d8fb0","established":"#9a968c","historical_no_ch_number":"#b23b3b","unknown_age":"#d9d6cd"}
def comp(df):
    d=df[(df.coarse_class!="founding_member")&df.entry_year.notna()].copy()
    d["w"]=(d.entry_year//5*5).astype(int); wins=sorted(d.w.unique())
    return {"windows":[f"{w}-{w+4}" for w in wins],
            "series":{c:[int(((d.w==w)&(d.coarse_class==c)).sum()) for w in wins] for c in CB}}
data={"FTSE100":comp(f),"S&P500":comp(s)}
html=f"""<!doctype html><html><head><meta charset=utf-8><title>Are new index members genuinely new?</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>body{{font-family:-apple-system,Segoe UI,Arial;max-width:1000px;margin:24px auto;color:#222;padding:0 16px}}
h1{{font-size:22px}} .sub{{color:#666}} .box{{height:330px;margin:8px 0 26px}} .note{{font-size:12.5px;color:#777}}
.card{{background:#faf9f6;border:1px solid #e6e5df;border-radius:10px;padding:14px 18px;margin:14px 0}}</style></head><body>
<h1>Are "new" index members genuinely new companies?</h1>
<p class="sub">First-time entrants to the FTSE 100 &amp; S&amp;P 500 by 5-year window. The youngest-at-entry cases
were adjudicated against sources; each carries a source URL in the classified CSVs.</p>
<div class="card"><b>Headline.</b> Almost every entrant that <i>looks</i> new is an established business arriving via a
<b>corporate action</b> — a spin-off, merger, demutualisation or reincorporation — not a genuinely new company.
Among the youngest-at-entry cohort, the S&amp;P amber cases were <b>100% corporate actions</b> (18 spin-offs, 8 mergers,
2 renames; zero new businesses); on the FTSE side only <b>Energis</b> was a true new-business entrant.</div>
<h3>FTSE 100</h3><div class="box"><canvas id="ftse"></canvas></div>
<h3>S&amp;P 500</h3><div class="box"><canvas id="sp"></canvas></div>
<p class="note">Provisional bucket = young-at-entry (≤12y) that passed the rule filters but has NOT yet been
source-adjudicated (so may still contain corporate actions). Founding members (index inception) excluded.
"Historical — no reliable CH number" = wrong-namesake match, quarantined. Counts absolute, so thin windows show thin.</p>
<script>const D={json.dumps(data)};const LAB={json.dumps(LAB)},COL={json.dumps(COL)};
function draw(cid,k){{const d=D[k];const ds=Object.keys(d.series).map(c=>({{label:LAB[c],data:d.series[c],backgroundColor:COL[c],stack:'s'}}));
new Chart(document.getElementById(cid),{{type:'bar',data:{{labels:d.windows,datasets:ds}},options:{{responsive:true,maintainAspectRatio:false,
scales:{{x:{{stacked:true}},y:{{stacked:true,title:{{display:true,text:'first-time entrants'}}}}}},plugins:{{legend:{{position:'bottom',labels:{{boxWidth:12,font:{{size:11}}}}}}}}}}}});}}
draw('ftse','FTSE100');draw('sp','S&P500');</script></body></html>"""
open(os.path.join(HERE,"entrant_analysis.html"),"w").write(html)
print("\nregenerated entrant_analysis.html")
