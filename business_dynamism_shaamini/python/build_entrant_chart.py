#!/usr/bin/env python3
"""Render entrant_analysis.html — stacked composition of index entrants per 5-yr
window (FTSE100 & S&P500) + the 'genuinely new' share line. Honest: shows absolute
counts (so small-N windows are visible), labels the data-gap bucket, notes caveats."""
import os, json, pandas as pd, numpy as np
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
f=pd.read_csv(os.path.join(HERE,"ftse_entrants_classified.csv"))
s=pd.read_csv(os.path.join(HERE,"sp500_entrants_classified.csv"))
CLASSES=["genuinely_new_provisional","very_new_adjudicate","wrapper_reincorp","new_entity_renamed",
         "spac_shell","re_entry","established","historical_unmatched","unknown_age"]
LABEL={"genuinely_new_provisional":"Genuinely new (provisional)","very_new_adjudicate":"Very new — adjudicate",
       "wrapper_reincorp":"Wrapper / reincorporation","new_entity_renamed":"New entity, renamed",
       "spac_shell":"SPAC / shell","re_entry":"Re-entry (was in before)","established":"Established business",
       "historical_unmatched":"Historical — no reliable CH number","unknown_age":"Unknown age (data gap)"}
COLOR={"genuinely_new_provisional":"#2e8b57","very_new_adjudicate":"#e6a417","wrapper_reincorp":"#c0562e",
       "new_entity_renamed":"#d9772b","spac_shell":"#9b59b6","re_entry":"#6d8fb0","established":"#9a968c",
       "historical_unmatched":"#b23b3b","unknown_age":"#d9d6cd"}
def comp(df):
    d=df[(df.provisional_class!="founding_member")&df.entry_year.notna()].copy()
    d["window"]=(d.entry_year//5*5).astype(int)
    wins=sorted(d.window.unique())
    out={"windows":[str(w)+"s" if False else f"{w}-{w+4}" for w in wins],"series":{},"pct_new":[]}
    for c in CLASSES:
        out["series"][c]=[int(((d.window==w)&(d.provisional_class==c)).sum()) for w in wins]
    for w in wins:
        sub=d[d.window==w]; base=sub[~sub.provisional_class.isin(["unknown_age"])]
        newn=(base.provisional_class=="genuinely_new_provisional").sum()
        out["pct_new"].append(round(100*newn/len(base),0) if len(base) else None)
    return out
data={"FTSE100":comp(f),"S&P500":comp(s),
      "founding":{"FTSE100":int((f.provisional_class=="founding_member").sum()),
                  "S&P500":int((s.provisional_class=="founding_member").sum())}}
J=json.dumps(data)
html=f"""<!doctype html><html><head><meta charset=utf-8><title>Index entrants — genuinely new?</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>body{{font-family:-apple-system,Segoe UI,Arial;max-width:1000px;margin:24px auto;color:#222;padding:0 16px}}
h1{{font-size:22px}} .sub{{color:#666}} .box{{height:340px;margin:10px 0 30px}} .note{{font-size:12.5px;color:#777}}
.card{{background:#faf9f6;border:1px solid #e6e5df;border-radius:10px;padding:14px 18px;margin:16px 0}}</style></head><body>
<h1>Are new index members genuinely new companies?</h1>
<p class="sub">FTSE 100 & S&amp;P 500 — first-time entrants per 5-year window, by what kind of arrival they were.
Provisional, rule-based classification from the business-dynamism database. Founding members (index inception)
are excluded: <b>{data['founding']['FTSE100']}</b> FTSE, <b>{data['founding']['S&P500']}</b> S&amp;P.</p>
<div class="card"><b>How to read this.</b> "Genuinely new" (green) = the underlying business was young (≤12y) at entry
and shows no wrapper/rename/re-entry signal. "Very new / wrapper" (amber) = index-sized within ≤3 years of
incorporation — almost always a reincorporation, redomicile or spin-off rather than an organic new firm, and the
bucket that most needs source-based adjudication. Counts are absolute, so thin recent windows are visibly thin.</div>
<h3>FTSE 100</h3><div class="box"><canvas id="ftse"></canvas></div>
<h3>S&amp;P 500</h3><div class="box"><canvas id="sp"></canvas></div>
<p class="note">Provisional first pass. Caveats: CH incorporation date is the legal entity's, not the business's,
so wrappers understate true age (why the amber bucket exists); S&amp;P "unknown age" is a real data gap (missing
founded year) — not a finding; small annual entrant counts make single windows noisy; corporate-action lineage
(spin-off vs IPO vs redomicile) still needs source adjudication before the amber bucket is split.</p>
<script>const D={J};
function draw(cid, key){{const d=D[key];const ds=Object.keys(d.series).map(c=>({{label:{json.dumps(LABEL)}[c],
 data:d.series[c],backgroundColor:{json.dumps(COLOR)}[c],stack:'s'}}));
 new Chart(document.getElementById(cid),{{type:'bar',data:{{labels:d.windows,datasets:ds}},
 options:{{responsive:true,maintainAspectRatio:false,scales:{{x:{{stacked:true}},y:{{stacked:true,title:{{display:true,text:'first-time entrants'}}}}}},
 plugins:{{legend:{{position:'bottom',labels:{{boxWidth:12,font:{{size:11}}}}}},title:{{display:false}}}}}}}});}}
draw('ftse','FTSE100');draw('sp','S&P500');</script></body></html>"""
open(os.path.join(HERE,"entrant_analysis.html"),"w").write(html)
print("wrote entrant_analysis.html")
print("FTSE windows:",data["FTSE100"]["windows"])
print("FTSE genuinely_new by window:",data["FTSE100"]["series"]["genuinely_new_provisional"])
print("FTSE wrapper_reincorp by window:",data["FTSE100"]["series"]["wrapper_reincorp"])
