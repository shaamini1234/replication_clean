#!/usr/bin/env python3
"""build_site_data.py — the back end for the public site.

Everything the site displays is computed HERE, against the canonical DuckDB, and
written to ``vercel_site/data/site.json``. The front end (``vercel_site/index.html``)
performs no arithmetic: it looks up pre-formatted strings for the prose and passes
pre-built Chart.js specifications straight to Chart.js.

Contract with the front end
---------------------------
    {
      "meta":    {...}                     provenance (db path, build stamps)
      "figures": {"<key>": "<string>"}     every number/word that appears in prose
      "charts":  {"<canvas id>": <spec>}   Chart.js config + tick/tooltip label maps
      "text":    {"<key>": "<string>"}     data-derived labels (axis names, buttons)
    }

Run:
    python python/build_site_data.py                 # build
    python python/build_site_data.py --verify        # build + check every
                                                     # data-f / data-chart in the
                                                     # HTML resolves (wiring gate)

The DuckDB location is taken from $BD_DUCKDB, else the first candidate that exists.
Methodology notes (coverage cut-offs, region mapping, GVA definition) are recorded
inline next to the query that depends on them.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "vercel_site" / "data" / "site.json"
HTML = REPO / "vercel_site" / "index.html"

DB_CANDIDATES = [
    REPO / "database" / "business_dynamism_v2_20260824d.duckdb",
    REPO.parent
    / "business_dynamism-master"
    / "business_dynamism_shaamini"
    / "database"
    / "business_dynamism_v2_20260824d.duckdb",
]

# Design tokens — mirrored from index.html's :root so chart colours travel with
# the data (the front end holds no literals of its own).
PAL = {
    "navy": "#1f3864",
    "blue": "#2e6fb0",
    "teal": "#2a8f86",
    "amber": "#c8860a",
    "red": "#b5432f",
    "green": "#4a7a45",
    "mut": "#5c6270",
    "grid": "#eceae4",
    "grey": "#c9ccd2",
}
FILL = {
    "navy": "rgba(31,56,100,.07)",
    "green": "rgba(74,122,69,.07)",
    "red": "rgba(181,67,47,.08)",
    "blue": "rgba(46,111,176,.07)",
}


def resolve_db() -> Path:
    env = os.environ.get("BD_DUCKDB")
    if env:
        p = Path(env).expanduser()
        if not p.exists():
            sys.exit(f"BD_DUCKDB is set to {p} but that file does not exist.")
        return p
    for p in DB_CANDIDATES:
        if p.exists():
            return p
    sys.exit(
        "No DuckDB found. Set BD_DUCKDB=/path/to/business_dynamism_v2_*.duckdb.\n"
        "Looked in:\n  " + "\n  ".join(str(p) for p in DB_CANDIDATES)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Formatting — every string the page shows is produced by one of these.
# ─────────────────────────────────────────────────────────────────────────────

def i(n) -> str:
    """1234567 -> '1,234,567'"""
    return f"{round(float(n)):,}"


def compact(n) -> str:
    """7877348 -> '7.9M';  63080 -> '63k'"""
    n = float(n)
    if abs(n) >= 1e6:
        return f"{n / 1e6:.1f}M"
    if abs(n) >= 1e3:
        return f"{round(n / 1e3):,.0f}k"
    return f"{round(n):,}"


def approx(n, unit=1000) -> str:
    """Round to the nearest `unit` and format: 24383 -> '24,000'."""
    return i(round(float(n) / unit) * unit)


def pct(x, dp=0) -> str:
    return f"{float(x):.{dp}f} per cent"


def pctn(x, dp=1) -> str:
    return f"{float(x):.{dp}f}%"


def gbp_bn(x, dp=1) -> str:
    return f"£{float(x):.{dp}f}bn"


def gbp_m(x, dp=1) -> str:
    return f"£{float(x):.{dp}f} million"


def gbp_tn(x, dp=2) -> str:
    return f"£{float(x):.{dp}f} trillion"


def usd_m(x) -> str:
    return f"${round(float(x)):,}m"


def times(x, dp=2) -> str:
    return f"{float(x):.{dp}f} times"


ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def word(n) -> str:
    """18 -> 'eighteen'; 35 -> 'thirty-five'. Falls back to digits above 999."""
    n = int(round(float(n)))
    if n < 0:
        return "minus " + word(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        t, r = divmod(n, 10)
        return TENS[t] + (f"-{ONES[r]}" if r else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return ONES[h] + " hundred" + (f" and {word(r)}" if r else "")
    return i(n)


def range_words(a, b) -> str:
    """(18, 19) -> 'eighteen to nineteen'; (7, 7) -> 'seven'."""
    a, b = int(round(a)), int(round(b))
    lo, hi = min(a, b), max(a, b)
    return word(lo) if lo == hi else f"{word(lo)} to {word(hi)}"


def multiple_word(ratio) -> str:
    """7.39 -> 'sevenfold'. Below 1.5x, describe rather than multiply."""
    r = float(ratio)
    if r < 1.15:
        return "broadly flat"
    if r < 1.5:
        return "a partial"
    n = int(round(r))
    return f"{word(n)}fold" if n <= 20 else f"{i(n)}-fold"


def times_word(ratio) -> str:
    """4.02 -> 'four times'; 2.4 -> '2.4 times'."""
    r = float(ratio)
    return f"{word(r)} times" if abs(r - round(r)) < 0.1 and r <= 20 else f"{r:.1f} times"


FRACTIONS = [
    (1 / 10, "a tenth"), (1 / 6, "a sixth"), (1 / 5, "a fifth"), (1 / 4, "a quarter"),
    (1 / 3, "a third"), (2 / 5, "two-fifths"), (1 / 2, "half"), (3 / 5, "three-fifths"),
    (2 / 3, "two-thirds"), (3 / 4, "three-quarters"), (4 / 5, "four-fifths"),
]


def fraction_word(x) -> str:
    """0.49 -> 'half'; 0.34 -> 'a third'. x is a proportion in [0,1]."""
    x = float(x)
    return min(FRACTIONS, key=lambda f: abs(f[0] - x))[1]


def change_phrase(frm, to) -> str:
    """Direction + magnitude of a change, as words: 'fell by roughly half'."""
    frm, to = float(frm), float(to)
    if frm == 0:
        return "changed"
    delta = (to - frm) / frm
    if abs(delta) < 0.03:
        return "was essentially unchanged"
    verb = "rose" if delta > 0 else "fell"
    mag = abs(delta)
    if mag >= 1:
        return f"{verb} {multiple_word(1 + mag)}"
    return f"{verb} by roughly {fraction_word(mag)}"


def gap_phrase(index_value, base=100.0) -> str:
    """104.2 -> 'about a twentieth above'; 93.6 -> 'roughly a sixteenth below'."""
    d = (float(index_value) - base) / base
    return f"{pct(abs(d) * 100)} {'above' if d >= 0 else 'below'}"


MONTHS = [
    "", "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]


def month_name(d: date) -> str:
    return MONTHS[d.month]


# ─────────────────────────────────────────────────────────────────────────────
# Axis ticks — computed here so the front end never formats a number.
# ─────────────────────────────────────────────────────────────────────────────

def nice_ticks(vmax, count=5, vmin=0):
    """Round tick values covering [vmin, vmax] — returns (min, max, step, values)."""
    vmax = float(vmax)
    if vmax <= vmin:
        vmax = vmin + 1
    raw = (vmax - vmin) / count
    mag = 10 ** int(f"{raw:e}".split("e")[1])
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if step >= raw:
            break
    top = step * (int(vmax / step) + (0 if abs(vmax % step) < 1e-9 else 1))
    vals, v = [], vmin
    while v <= top + 1e-9:
        vals.append(round(v, 10))
        v += step
    return vmin, top, step, vals


def tick_map(values, fmt) -> dict:
    """{tick value -> pre-formatted label}. Keys must match JavaScript's
    String(value) exactly, so integers are written without an exponent."""
    out = {}
    for v in values:
        key = str(int(v)) if float(v).is_integer() else repr(float(v))
        out[key] = fmt(v)
    return out


def axis(title=None, grid=True, ticks=None, **kw):
    a = {"grid": {"color": PAL["grid"]} if grid else {"display": False}}
    if title:
        a["title"] = {"display": True, "text": title}
    if ticks:
        a["ticks"] = ticks
    a.update(kw)
    return a


def base_options(legend=False, index_axis=None, interaction_index=False):
    o = {
        "responsive": True,
        "maintainAspectRatio": False,
        "plugins": {
            "legend": (
                {
                    "position": "top",
                    "align": "end",
                    "labels": {"usePointStyle": True, "boxWidth": 8},
                }
                if legend
                else {"display": False}
            )
        },
    }
    if index_axis:
        o["indexAxis"] = index_axis
    if interaction_index:
        o["interaction"] = {"mode": "index", "intersect": False}
    return o


# ─────────────────────────────────────────────────────────────────────────────
# Region mapping — postcode AREA (leading letters) to region.
# Mirrors sql/11_add_region.sql, the repo's canonical mapping. Approximate:
# an exact region needs the ONS Postcode Directory.
# ─────────────────────────────────────────────────────────────────────────────
POSTCODE_REGION = {
    **{a: "London" for a in "E EC N NW SE SW W WC BR CR DA EN HA IG KT RM SM TW UB WD".split()},
    **{a: "South East" for a in "BN CT GU ME MK OX PO RG RH SL SO TN".split()},
    **{a: "South West" for a in "BA BH BS DT EX GL PL TA TQ TR SN SP".split()},
    **{a: "East of England" for a in "AL CB CM CO IP LU NR PE SG SS".split()},
    **{a: "West Midlands" for a in "B CV DY WS WV WR TF ST".split()},
    **{a: "East Midlands" for a in "DE LE LN NG NN".split()},
    **{a: "Yorkshire & Humber" for a in "BD DN HD HG HU HX LS S WF YO".split()},
    **{a: "North West" for a in "BB BL CA CH CW FY L LA M OL PR SK WA WN".split()},
    **{a: "North East" for a in "DH DL NE SR TS".split()},
    **{a: "Wales" for a in "CF LD LL NP SA SY".split()},
    **{a: "Scotland" for a in "AB DD DG EH FK G HS IV KA KW KY ML PA PH TD ZE".split()},
    "BT": "Northern Ireland",
}

# A postcode's area is its leading 1–2 letters (always followed by a digit).
PC_AREA = r"regexp_extract(upper({col}),'^[A-Z]{{1,2}}')"
# First postcode appearing in a Gazette notice — the company's registered office
# in the notice body. Dead firms have left the `companies` snapshot, so the
# notice text is the only regional signal available for them.
PC_IN_TEXT = r"regexp_extract(upper(notice_text),'([A-Z]{1,2})[0-9][0-9A-Z]?\s+[0-9][A-Z]{2}',1)"

# UK technical recessions (two or more consecutive quarters of falling GDP),
# as fractional years so a band can be drawn on an annual axis. Source: ONS,
# "Communicating the UK Economic Cycle" and the quarterly GDP bulletins
# (pre-recession quarters 1990 Q2 and 2008 Q1; 2020 Q1-Q2). The 2023 Q3-Q4
# technical recession is omitted: at two quarters it renders as a hairline on an
# annual axis rather than a band a reader can see.
RECESSIONS = [
    (1990.50, 1991.75, "early-1990s recession"),
    (2008.25, 2009.50, "global financial crisis"),
    (2020.00, 2020.50, "pandemic"),
]

# Coverage thresholds — the rules that decide where a series starts and stops.
PARTIAL_YEAR_RATIO = 0.5   # a year holding < 50% of the trailing norm is partial
MIN_INDUSTRY_FIRMS = 20000  # industry rate needs a large enough base (sql/10)
# No single UK company-year can post staff costs or an operating profit of this
# size: the largest legitimate value added in the panel is about £2bn, whereas a
# handful of rows carry values in the hundreds of billions — a scale/sign error in
# the filed-accounts extraction. Rows beyond the ceiling are excluded from every
# value-added figure and the count of exclusions is published.
GVA_CEILING = 10e9
GVA_PLAUSIBLE = (
    "abs(staff_costs) < 10e9 and abs(operating_profit) < 10e9"
)
MIN_OBSERVED_AGE = 3        # a survival curve needs at least this much follow-up
MIN_AT_RISK_SHARE = 0.25    # a hazard estimate needs a quarter of the population still observed
PANEL_MIN_SHARE = 0.33      # a balanced panel must retain a third of the index
INDEX_SIZE = {"ftse": 100, "sp": 500}


class Build:
    """Every figure on the site is produced by a method on this class."""

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.con = con
        self.sector_table()
        self.con.execute("create or replace temp table pcr(area varchar, region varchar)")
        self.con.executemany(
            "insert into pcr values (?, ?)", list(POSTCODE_REGION.items())
        )

    # -- query helpers --------------------------------------------------------
    def rows(self, sql: str) -> list[tuple]:
        return self.con.execute(sql).fetchall()

    def val(self, sql):
        r = self.con.execute(sql).fetchone()
        return None if r is None else r[0]

    # -- coverage rules ------------------------------------------------------
    def gazette_span(self) -> tuple[int, int, date]:
        """(first complete year, last complete year, latest notice date)."""
        last_notice = self.val("select max(event_date) from gazette_events")
        by_year = dict(
            self.rows(
                "select extract(year from death_date)::int, count(*) from exit_events "
                "where exit_class='insolvent' and death_date is not null group by 1"
            )
        )
        years = sorted(by_year)
        first = years[0]
        # drop a ramp-up first year that holds far less than the year after it
        if by_year[first] < PARTIAL_YEAR_RATIO * by_year[years[1]]:
            first = years[1]
        last_complete = (
            last_notice.year
            if (last_notice.month, last_notice.day) == (12, 31)
            else last_notice.year - 1
        )
        return first, last_complete, last_notice

    def last_complete_birth_year(self) -> int:
        """Incorporations come from a register snapshot; its tail year is partial."""
        by_year = dict(
            self.rows(
                "select birth_year, count(*) from firm_master "
                "where birth_year is not null group by 1"
            )
        )
        years = sorted(by_year)
        last = years[0]
        for y in years[1:]:
            prior = sorted(by_year.get(y - k, 0) for k in (1, 2, 3))[1]  # median of 3
            if prior and by_year[y] >= PARTIAL_YEAR_RATIO * prior:
                last = y
        return last

    # -- Part I: the population ---------------------------------------------
    def head(self) -> dict:
        uk, fy, gz = self.rows(
            "select (select count(*) from firm_master),"
            "       (select count(*) from combined_firm_year),"
            "       (select count(*) from gazette_events)"
        )[0]
        ftse = self.val("select count(distinct coalesce(company_number, company_name)) from ftse100_membership")
        sp = self.val("select count(distinct ticker) from sp500_membership")
        return {"uk_firms": uk, "firm_years": fy, "gazette": gz, "ftse_n": ftse, "sp_n": sp}

    def pulse(self, y0: int, y1: int) -> list[tuple]:
        births = dict(
            self.rows(
                f"select birth_year, count(*) from firm_master "
                f"where birth_year between {y0} and {y1} group by 1"
            )
        )
        ins = dict(
            self.rows(
                f"select extract(year from death_date)::int, count(*) from exit_events "
                f"where exit_class='insolvent' and extract(year from death_date) "
                f"between {y0} and {y1} group by 1"
            )
        )
        return [(y, births.get(y, 0), ins.get(y, 0)) for y in range(y0, y1 + 1)]

    def mechanisms(self) -> list[dict]:
        """Terminal Gazette notice types, most frequent first. Labels are derived
        from the event_type token, so a new type appears without a code change."""
        rows = self.rows(
            "select event_type, count(*) n from gazette_events "
            "where event_type is not null and event_type <> 'unknown' group by 1 order by 2 desc, 1"
        )
        skip = ("restored_to_register", "removed_from_register")
        out = []
        for t, n in rows:
            if t in skip:
                continue
            label = t.replace("_", " ")
            label = {
                "creditors voluntary winding up": "Creditors' voluntary liquidation",
                "members voluntary winding up": "Members' voluntary (solvent)",
                "petition to wind up": "Petition to wind up",
                "winding up order court": "Winding-up order (court)",
            }.get(label, label[:1].upper() + label[1:])
            out.append({"key": t, "label": label, "n": n, "solvent": "members_voluntary" in t})
        return out

    def age_at_insolvency(self) -> tuple[list[tuple], float]:
        rows = self.rows(
            "with a as (select extract(year from death_date)::int - birth_year age "
            "  from firm_master where exit_class='insolvent' and birth_year is not null "
            "  and death_date is not null) "
            "select age, count(*) from a where age between 0 and 60 group by 1 order by 1"
        )
        med = self.val(
            "select median(extract(year from death_date)::int - birth_year) from firm_master "
            "where exit_class='insolvent' and birth_year is not null and death_date is not null"
        )
        return rows, float(med)

    def geography(self) -> dict:
        live = self.rows(
            f"select pcr.region, count(*) n from companies c "
            f"join pcr on pcr.area = {PC_AREA.format(col='c.\"RegAddress_PostCode\"')} "
            f"group by 1 order by 2 desc, 1"
        )
        ins = self.rows(
            # min(), not any_value(): any_value picks an arbitrary row per group, so the
        # same query returned different areas between identical runs and c_geo's
        # counts moved. Where a company has several Gazette notices with different
        # registered offices, min() picks the same one every time.
        f"with n as (select company_number, min({PC_IN_TEXT}) area from gazette_events "
            f"          where company_number is not null group by 1) "
            f"select pcr.region, count(*) c from exit_events e "
            f"join n on n.company_number = e.company_number_norm "
            f"join pcr on pcr.area = n.area "
            f"where e.exit_class='insolvent' group by 1 order by 2 desc, 1"
        )
        mapped = sum(n for _, n in ins)
        total_ins = self.val("select count(*) from exit_events where exit_class='insolvent'")
        return {
            "live": live,
            "insolvent": ins,
            "unmapped_share": (total_ins - mapped) / total_ins,
        }

    def cycle(self, y0: int, last_notice: date) -> list[tuple]:
        rows = self.rows(
            f"select extract(year from death_date)::int y, count(*) from exit_events "
            f"where exit_class='insolvent' and extract(year from death_date) >= {y0} "
            f"group by 1 order by 1"
        )
        return [(y, n, y == last_notice.year) for y, n in rows]

    def exit_mix(self, y0: int, y1: int) -> list[tuple]:
        return self.rows(
            f"select extract(year from death_date)::int y, "
            f"       round(100.0*count(*) filter(where exit_class='insolvent')/count(*), 1) "
            f"from exit_events where extract(year from death_date) between {y0} and {y1} "
            f"group by 1 order by 1"
        )

    def size_rates(self) -> tuple[list[tuple], float]:
        rows = dict(
            (s or "unknown", (n, float(p)))
            for s, n, p in self.rows(
                "select size_class, count(*) n, "
                "round(100.0*count(*) filter(where exit_class='insolvent')/count(*), 1) p "
                "from firm_master group by 1"
            )
        )
        order = ["micro", "small", "medium", "large"]
        band = [(b, rows[b][1]) for b in order if b in rows]
        return band, rows.get("unknown", (0, 0.0))[1]

    def industry_rates(self) -> list[tuple]:
        """The six highest failure rates among industries with a base of at least
        MIN_INDUSTRY_FIRMS firms, plus the median rate across all qualifying
        industries as the comparator."""
        rows = self.rows(
            f"select sic_desc, round(100.0*count(*) filter(where exit_class='insolvent')"
            f"/count(*), 1) p, count(*) n from firm_master where sic_desc is not null "
            f"group by 1 having count(*) > {MIN_INDUSTRY_FIRMS} order by p desc, sic_desc"
        )
        rates = sorted(float(p) for _, p, _ in rows)
        median = rates[len(rates) // 2]
        return [(d, float(p)) for d, p, _ in rows[:6]], median, len(rows)

    def cohorts(self, gazette_first: int, last_complete: int) -> list[tuple]:
        """Share of a birth cohort insolvent within five years. Only cohorts whose
        whole five-year window sits inside complete Gazette years qualify."""
        y0, y1 = gazette_first, last_complete - 5
        return [
            (y, float(p))
            for y, p in self.rows(
                f"select birth_year, round(100.0*count(*) filter(where exit_class='insolvent' "
                f"  and extract(year from death_date)::int - birth_year <= 5)/count(*), 1) "
                f"from firm_master where birth_year between {y0} and {y1} group by 1 order by 1"
            )
        ]

    def gva(self) -> dict:
        """GVA (income method) = staff costs + operating profit. Depreciation is
        the third term of the textbook definition; the filed-accounts panel does
        not carry it, so it is excluded and the gap stated on the page."""
        all_rows, both = self.rows(
            "select count(*), "
            f"count(*) filter(where staff_costs is not null and operating_profit is not null "
            f"                 and {GVA_PLAUSIBLE}) "
            "from combined_firm_year"
        )[0]
        excluded = self.val(
            "select count(*) from combined_firm_year where staff_costs is not null "
            f"and operating_profit is not null and not ({GVA_PLAUSIBLE})"
        )
        return {
            "computable_pct": 100.0 * both / all_rows,
            "excluded": int(excluded),
        }

    # -- Part III: listed firms ---------------------------------------------
    def sector_table(self):
        """Register the committed classification as `ftse100_sector_manual`.

        Keyed on company_number, not ticker. London tickers are reused — RSA maps
        to three different companies, GAA to three, WPP to two — so a ticker join
        hands one company's sector to another's index membership. The keyed file
        (build_ftse_sector_crosswalk.py) resolves each row to a company_number
        using the ticker AND the year span, which separates the claimants.

        One company can still appear twice, under an old and a new ticker
        (BSY/SKY, REL/RELX). Those agree on sector in every case but one, so the
        view keeps the row backed by more composition observations and the
        disagreement is reported by --verify rather than silently resolved.
        """
        if not FTSE_SECTORS_KEYED.exists():
            sys.exit(
                f"Missing {FTSE_SECTORS_KEYED.relative_to(REPO)} — "
                f"run python/build_ftse_sector_crosswalk.py first."
            )
        self.con.execute(
            "create or replace temp view ftse100_sector_keyed_raw as "
            f"select code, company_number, company_name, sector as sector_manual, "
            f"basis as source_note, match_basis, match_years "
            f"from read_csv_auto('{FTSE_SECTORS_KEYED}', header=true, all_varchar=true) "
            f"where company_number is not null and company_number <> ''"
        )
        # one sector per company: prefer the ticker observed over more years
        self.con.execute(
            "create or replace temp view ftse100_sector_manual as "
            "select company_number, code, company_name, sector_manual, source_note "
            "from ("
            "  select *, row_number() over ("
            "    partition by company_number "
            "    order by try_cast(split_part(match_years,'-',2) as integer) "
            "           - try_cast(split_part(match_years,'-',1) as integer) desc, code"
            "  ) rn from ftse100_sector_keyed_raw"
            ") where rn = 1"
        )

    def sector_conflicts(self) -> list[tuple]:
        """Companies whose duplicate sector rows disagree — a signal that the
        underlying ticker -> company_number record is wrong, not that the sector
        is ambiguous."""
        return self.rows(
            "select company_number, string_agg(distinct code, '/'), "
            "string_agg(distinct sector_manual, ' vs ') "
            "from ftse100_sector_keyed_raw group by 1 "
            "having count(distinct sector_manual) > 1"
        )

    def ftse_sector_view(self):
        """company_number -> classified sector, via the index composition record
        (the statutory SIC codes are holding-company dominated)."""
        self.con.execute(
            "create or replace temp view ftse_sector as "
            "select distinct cp.company_number cn, sm.sector_manual sector "
            "from ftse100_compositions cp join ftse100_sector_manual sm "
            "  on sm.company_number = cp.company_number "
            "where cp.company_number is not null"
        )

    def coverage_years(self, table: str, year_col: str, cols: list[str], share: float) -> list[int]:
        """Years whose non-null coverage reaches `share` of the best-covered year."""
        cond = " and ".join(f"{c} is not null" for c in cols)
        rows = self.rows(
            f"select {year_col} y, count(*) filter(where {cond}) n from {table} "
            f"group by 1 having n > 0 order by 1"
        )
        if not rows:
            return []
        best = max(n for _, n in rows)
        return [int(y) for y, n in rows if n >= share * best]

    def coverage_years_min(self, table: str, year_col: str, cols: list[str], min_rows: int) -> list[int]:
        """Years holding at least `min_rows` complete observations."""
        cond = " and ".join(f"{c} is not null" for c in cols)
        return [
            int(y)
            for y, n in self.rows(
                f"select {year_col} y, count(*) filter(where {cond}) n from {table} "
                f"group by 1 order by 1"
            )
            if n >= min_rows
        ]

    def usable_market_cap_years(self, table: str, year_col: str, mc_col: str, index: str,
                                coverage: float) -> tuple[list[int], list[int], float]:
        """Years whose market-capitalisation record is both well covered and
        plausible.

        Some share counts in the source are not split-adjusted, which inflates a
        handful of constituent market caps by the split ratio and so corrupts any
        share-of-total measure for that year. The gate: no constituent may exceed
        a ceiling of twice the median largest-constituent share observed across
        the well-covered years. Excluded years are reported on the page rather
        than silently dropped."""
        size = INDEX_SIZE[index]
        shares = {
            int(y): float(p)
            for y, p in self.rows(
                f"select {year_col} y, 100.0*max({mc_col})/sum({mc_col}) from {table} "
                f"where {mc_col} is not null group by 1"
            )
        }
        well_covered = self.coverage_years_min(table, year_col, [mc_col], round(0.9 * size))
        reference = sorted(shares[y] for y in well_covered) or sorted(shares.values())
        median = reference[len(reference) // 2]
        ceiling = 2 * median
        candidates = self.coverage_years_min(table, year_col, [mc_col], round(coverage * size))
        keep = [y for y in candidates if shares[y] <= ceiling]
        drop = [y for y in candidates if shares[y] > ceiling]
        return keep, drop, ceiling

    def balanced_panel(self, cols: list[str], last_year: int) -> tuple[int, list[str]]:
        """Longest window ending at `last_year` for which at least a third of the
        index has an unbroken series. Returns (window start, constituents)."""
        cond = " and ".join(f"{c} is not null" for c in cols)
        first = int(
            self.val(
                f"select min(year) from ftse100_consolidated where {cond} and company_number is not null"
            )
        )
        floor = round(PANEL_MIN_SHARE * INDEX_SIZE["ftse"])
        for start in range(first, last_year + 1):
            span = last_year - start + 1
            members = [
                r[0]
                for r in self.rows(
                    f"select company_number from ftse100_consolidated "
                    f"where year between {start} and {last_year} and {cond} "
                    f"and company_number is not null group by 1 "
                    f"having count(distinct year) = {span}"
                )
            ]
            if len(members) >= floor:
                return start, members
        return last_year, []

    def ftse_value_panel(self, last_year: int) -> dict:
        start, members = self.balanced_panel(["market_cap_gbp"], last_year)
        lst = "','".join(members)
        rows = self.rows(
            f"select year, sum(market_cap_gbp) v from ftse100_consolidated "
            f"where year between {start} and {last_year} and company_number in ('{lst}') "
            f"group by 1 order by 1"
        )
        vals = {int(y): float(v) for y, v in rows}
        base = self.base_year(vals)
        return {
            "n": len(members),
            "members": members,
            "start": start,
            "base": base,
            "series": [(y, vals[y], 100.0 * vals[y] / vals[base]) for y in sorted(vals)],
        }

    def ftse_dividend_panel(self, last_year: int, base: int) -> dict:
        """Total cash dividends of a balanced panel: pence per share x shares."""
        start, members = self.balanced_panel(
            ["annual_dividend_pence", "shares_outstanding"], last_year
        )
        lst = "','".join(members)
        rows = self.rows(
            f"select year, sum(annual_dividend_pence/100.0 * shares_outstanding) v "
            f"from ftse100_consolidated where year between {start} and {last_year} "
            f"and company_number in ('{lst}') group by 1 order by 1"
        )
        vals = {int(y): float(v) for y, v in rows}
        base = base if base in vals else self.base_year(vals)
        return {
            "n": len(members),
            "start": start,
            "base": base,
            "series": [(y, vals[y] / 1e9, 100.0 * vals[y] / vals[base]) for y in sorted(vals)],
        }

    @staticmethod
    def base_year(vals: dict) -> int:
        """The year before the sharpest fall in the series — the pre-crisis peak."""
        years = sorted(vals)
        worst, base = 0.0, years[0]
        for prev, cur in zip(years, years[1:]):
            drop = (vals[prev] - vals[cur]) / vals[prev]
            if drop > worst:
                worst, base = drop, prev
        return base

    def churn(self, table: str, y0: int, y1: int) -> list[tuple]:
        """Constituents joining and leaving each year. The index's founding
        backfill (a whole cohort dated to day one) is excluded by the window."""
        joined = dict(
            self.rows(
                f"select extract(year from start_date)::int y, count(*) from {table} "
                f"where start_date is not null group by 1"
            )
        )
        left = dict(
            self.rows(
                f"select extract(year from end_date)::int y, count(*) from {table} "
                f"where end_date is not null group by 1"
            )
        )
        return [(y, joined.get(y, 0), left.get(y, 0)) for y in range(y0, y1 + 1)]

    def sp_median_net_income(self) -> list[tuple]:
        years = self.coverage_years(
            "sp500_consolidated", "fiscal_year", ["net_income"], PARTIAL_YEAR_RATIO
        )
        y0, y1 = min(years), max(years)
        return [
            (int(y), float(v) / 1e6)
            for y, v in self.rows(
                f"select fiscal_year, median(net_income) from sp500_consolidated "
                f"where fiscal_year between {y0} and {y1} and net_income is not null "
                f"group by 1 order by 1"
            )
            if int(y) in years
        ]

    def gics_sectors(self) -> list[str]:
        """The canonical sector vocabulary — taken from the hand-classification,
        which is GICS-style and complete. sp500_consolidated.sector also holds
        SIC descriptions for some rows; those are excluded by this filter."""
        return [r[0] for r in self.rows("select distinct sector_manual from ftse100_sector_manual order by 1")]

    def sector_value_shares(self, year: int, sectors: list[str]) -> dict:
        lst = "','".join(sectors)
        sp = {
            s: float(p)
            for s, p in self.rows(
                f"select sector, 100.0*sum(market_cap)/sum(sum(market_cap)) over() "
                f"from sp500_consolidated where fiscal_year = {year} and market_cap is not null "
                f"and sector in ('{lst}') group by 1"
            )
        }
        ftse = {
            s: float(p)
            for s, p in self.rows(
                f"select sm.sector_manual, 100.0*sum(cp.market_cap_gbp)/sum(sum(cp.market_cap_gbp)) over() "
                f"from ftse100_compositions cp join ftse100_sector_manual sm "
                f"  on sm.company_number = cp.company_number "
                f"where cp.year = {year} and cp.market_cap_gbp is not null group by 1"
            )
        }
        return {"sp": sp, "ftse": ftse}

    def sp_sector_share_series(self, sector: str) -> list[tuple]:
        """One sector's share of S&P market value, per year.

        Denominator is market value that CARRIES a sector, not all market value.
        The two differ whenever sector coverage is incomplete, and the numerator
        can only ever count classified rows — so mixing them understates the
        share by exactly the unclassified fraction. That fraction used to be
        huge in early years (sector came from the live constituent list, so every
        company that had since exited was unclassified) which pushed the early
        part of this series down and manufactured a spurious upward trend.
        """
        years, _, _ = self.usable_market_cap_years(
            "sp500_consolidated", "fiscal_year", "market_cap", "sp", PARTIAL_YEAR_RATIO
        )
        y0, y1 = min(years), max(years)
        sectors = self.gics_sectors()
        lst = "','".join(sectors)
        return [
            (int(y), float(p))
            for y, p in self.rows(
                f"select fiscal_year, 100.0*sum(case when sector = '{sector}' then market_cap else 0 end)"
                f"/nullif(sum(market_cap), 0) from sp500_consolidated "
                f"where fiscal_year between {y0} and {y1} "
                f"and market_cap is not null and sector in ('{lst}') group by 1 order by 1"
            )
            if int(y) in years
        ]

    def sp_sector_coverage(self, year: int) -> float:
        """Share of that year's S&P market value that carries a GICS sector.

        The honesty check on every sector chart: a share computed over 47% of
        index value is not a share of the index. Surfaced as a figure so the
        page can state it rather than imply full coverage.
        """
        lst = "','".join(self.gics_sectors())
        v = self.val(
            f"select 100.0*sum(case when sector in ('{lst}') then market_cap else 0 end)"
            f"/nullif(sum(market_cap), 0) from sp500_consolidated "
            f"where fiscal_year = {year} and market_cap is not null"
        )
        return float(v or 0.0)

    def ftse_membership_sectors(self) -> dict:
        """Sector shares of FTSE 100 membership (count-based), every year the
        composition record covers at least half an index."""
        rows = self.rows(
            "select cp.year, sm.sector_manual, count(*) n from ftse100_compositions cp "
            "join ftse100_sector_manual sm on sm.company_number = cp.company_number group by 1, 2"
        )
        per_year: dict[int, dict[str, float]] = {}
        for y, s, n in rows:
            per_year.setdefault(int(y), {})[s] = float(n)
        out = {}
        for y, d in per_year.items():
            tot = sum(d.values())
            if tot >= 0.5 * INDEX_SIZE["ftse"]:
                out[y] = {s: round(100.0 * n / tot, 1) for s, n in d.items()}
        return dict(sorted(out.items()))

    def valuation_gap(self, year: int) -> dict:
        self.ftse_sector_view()
        sp_mb = float(self.val(
            f"select median(market_cap/nullif(total_assets,0)) from sp500_consolidated "
            f"where fiscal_year = {year} and market_cap is not null and total_assets > 0"
        ))
        sp_ex = float(self.val(
            f"select median(market_cap/nullif(total_assets,0)) from sp500_consolidated "
            f"where fiscal_year = {year} and sector <> 'Financials' and market_cap is not null "
            f"and total_assets > 0"
        ))
        ftse_mb = float(self.val(
            f"select median(market_cap_gbp/nullif(total_assets,0)) from ftse100_consolidated "
            f"where year = {year} and market_cap_gbp is not null and total_assets > 0"
        ))
        ftse_ex = float(self.val(
            f"select median(f.market_cap_gbp/nullif(f.total_assets,0)) from ftse100_consolidated f "
            f"left join ftse_sector s on s.cn = f.company_number "
            f"left join ftse100_sector_manual t on t.company_number = f.company_number "
            f"where f.year = {year} and coalesce(s.sector, t.sector_manual) <> 'Financials' "
            f"and f.market_cap_gbp is not null and f.total_assets > 0"
        ))
        n = int(self.val(
            f"select count(*) from ftse100_consolidated where year = {year} "
            f"and market_cap_gbp is not null and total_assets > 0"
        ))
        first_fund = int(self.val("select min(year) from ftse100_consolidated where total_assets is not null"))
        return {
            "year": year, "sp_mb": sp_mb, "ftse_mb": ftse_mb,
            "sp_mb_exfin": sp_ex, "ftse_mb_exfin": ftse_ex,
            "ftse_n": n, "ftse_first_fundamentals_year": first_fund,
        }

    def concentration(self) -> dict:
        """Top-ten share of index value. Requires near-complete coverage (90% of
        the index), otherwise the denominator is missing constituents."""
        sp_years, sp_dropped, ceiling = self.usable_market_cap_years(
            "sp500_consolidated", "fiscal_year", "market_cap", "sp", 0.9
        )
        sp = [
            (int(y), float(p))
            for y, p in self.rows(
                "with r as (select fiscal_year y, market_cap mc, row_number() over "
                "(partition by fiscal_year order by market_cap desc, cik) rn from sp500_consolidated "
                "where market_cap is not null) select y, 100.0*sum(mc) filter(where rn<=10)/sum(mc) "
                "from r group by 1 order by 1"
            )
            if int(y) in sp_years
        ]
        ftse_years, ftse_dropped, _ = self.usable_market_cap_years(
            "ftse100_compositions", "year", "market_cap_gbp", "ftse", 0.9
        )
        ftse = [
            (int(y), float(p))
            for y, p in self.rows(
                "with r as (select year y, market_cap_gbp mc, row_number() over "
                "(partition by year order by market_cap_gbp desc, coalesce(company_number, code)) rn "
                "from ftse100_compositions "
                "where market_cap_gbp is not null) select y, 100.0*sum(mc) filter(where rn<=10)/sum(mc) "
                "from r group by 1 order by 1"
            )
            if int(y) in ftse_years
        ]
        return {
            "sp": sp, "ftse": ftse,
            "dropped": sorted(set(sp_dropped) | set(ftse_dropped)),
            "ceiling": ceiling,
        }

    def ch_extraction(self) -> dict:
        n, dissolved = self.rows(
            "select count(*), count(*) filter(where dissolution_date is not null) from ch_company_profile"
        )[0]
        return {"profiles": n, "dissolved": dissolved}


# ─────────────────────────────────────────────────────────────────────────────
# Chart-spec builders. A spec is plain JSON: {type, data, options, tickLabels}.
# `tickLabels` maps an axis id to {tick value -> label}; the front end installs a
# lookup callback. `dataset.tips` holds one pre-formatted tooltip line per point.
# ─────────────────────────────────────────────────────────────────────────────

def value_axis(title, vmax, fmt, position=None, grid=True, vmin=0, count=5):
    lo, hi, step, vals = nice_ticks(vmax, count=count, vmin=vmin)
    a = axis(title=title, grid=grid, ticks={"stepSize": step}, min=lo, max=hi)
    if position:
        a["position"] = position
    return a, tick_map(vals, fmt)


def line_ds(label, data, colour, tips, fill=None, width=2.5, point=2):
    ds = {
        "label": label,
        "data": data,
        "borderColor": PAL[colour],
        "backgroundColor": FILL.get(colour, PAL[colour]) if fill else PAL[colour],
        "fill": bool(fill),
        "tension": 0.3,
        "pointRadius": point,
        "borderWidth": width,
        "tips": tips,
    }
    return ds


def bar_ds(data, colours, tips, label=None, radius=4):
    ds = {"data": data, "backgroundColor": colours, "borderRadius": radius, "tips": tips}
    if label:
        ds["label"] = label
    return ds


def build_population(b: Build) -> tuple[dict, dict, dict, dict]:
    """Part I + II — the whole-population series (Companies House + Gazette)."""
    F: dict[str, str] = {}          # prose figures
    T: dict[str, str] = {}          # data-derived labels
    C: dict[str, dict] = {}         # chart specs

    gz_first, gz_last, last_notice = b.gazette_span()
    birth_last = b.last_complete_birth_year()

    # ── header ───────────────────────────────────────────────────────────────
    h = b.head()
    F["head_uk_firms"] = compact(h["uk_firms"])
    F["head_firm_years"] = compact(h["firm_years"])
    F["head_gazette"] = compact(h["gazette"])
    F["head_constituents"] = i(h["ftse_n"] + h["sp_n"])
    T["head_constituents_label"] = "FTSE&nbsp;100 + S&amp;P&nbsp;500 constituents tracked"

    # ── formation and dissolution ────────────────────────────────────────────
    pulse = b.pulse(gz_first, min(birth_last, gz_last))
    years = [r[0] for r in pulse]
    births = [r[1] for r in pulse]
    ins = [r[2] for r in pulse]
    peak_i = births.index(max(births))
    F["pulse_first_year"] = str(years[0])
    F["pulse_first_inc"] = approx(births[0])
    F["pulse_peak_year"] = str(years[peak_i])
    F["pulse_peak_inc"] = approx(births[peak_i])
    F["pulse_multiple"] = multiple_word(births[peak_i] / births[0])
    ya, ymap = value_axis("new companies", max(births), compact)
    y1a, y1map = value_axis("insolvencies", max(ins), compact, position="right", grid=False)
    C["c_pulse"] = {
        "type": "line",
        "data": {
            "labels": [str(y) for y in years],
            "datasets": [
                dict(line_ds("New companies (left)", births, "green",
                             [f"{i(v)} new companies" for v in births], fill=True, point=0),
                     yAxisID="y"),
                dict(line_ds("Insolvencies (right)", ins, "red",
                             [f"{i(v)} insolvencies" for v in ins], point=0),
                     yAxisID="y1"),
            ],
        },
        "options": {
            **base_options(legend=True, interaction_index=True),
            "scales": {"x": axis(grid=False), "y": ya, "y1": y1a},
        },
        "tickLabels": {"y": ymap, "y1": y1map},
        "bands": recession_bands([str(y) for y in years]),
    }

    # ── the cycle is needed early: the pulse prose quotes its recent average ──
    cyc = b.cycle(gz_first, last_notice)
    complete = [(y, n) for y, n, part in cyc if not part]
    F["pulse_insolv_avg"] = approx(sum(n for _, n in complete[-5:]) / 5)
    F["pulse_insolv_years"] = f"{complete[-5][0]}–{complete[-1][0]}"

    # ── dissolution mechanisms ───────────────────────────────────────────────
    mech = b.mechanisms()
    wind_up = [m for m in mech if "winding_up" in m["key"]]
    solvent = [m for m in mech if m["solvent"]]
    F["mech_top_label"] = mech[0]["label"].lower()
    if solvent and wind_up:
        share = solvent[0]["n"] / sum(m["n"] for m in wind_up)
        F["mech_solvent_pct"] = pct(share * 100)
    xa, xmap = value_axis(None, max(m["n"] for m in mech), compact)
    C["c_mech"] = {
        "type": "bar",
        "data": {
            "labels": [m["label"] for m in mech],
            "datasets": [bar_ds([m["n"] for m in mech],
                                [PAL["green"] if m["solvent"] else PAL["red"] for m in mech],
                                [f"{i(m['n'])} notices" for m in mech])],
        },
        "options": {**base_options(index_axis="y"), "scales": {"x": xa, "y": axis(grid=False)}},
        "tickLabels": {"x": xmap},
    }

    # ── age at dissolution ───────────────────────────────────────────────────
    ages, median_age = b.age_at_insolvency()
    F["age_median"] = f"{round(median_age)} yrs"
    ya, ymap = value_axis(None, max(n for _, n in ages), compact)
    C["c_age"] = {
        "type": "bar",
        "data": {
            "labels": [str(a) for a, _ in ages],
            "datasets": [dict(bar_ds([n for _, n in ages], PAL["amber"],
                                     [f"{i(n)} firms" for _, n in ages], radius=2),
                              barPercentage=1, categoryPercentage=1)],
        },
        "options": {
            **base_options(),
            "scales": {
                "x": axis(title="age at insolvency (years)", grid=False,
                          ticks={"maxTicksLimit": 13}),
                "y": ya,
            },
        },
        "tickLabels": {"y": ymap},
        "tooltipTitles": [f"Age {a}" for a, _ in ages],
    }

    # ── geography ────────────────────────────────────────────────────────────
    geo = b.geography()
    live_total = sum(n for _, n in geo["live"])
    F["geo_top_region"] = geo["live"][0][0]
    F["geo_top_pct"] = pct(100.0 * geo["live"][0][1] / live_total)
    F["geo_second_region"] = geo["live"][1][0]
    F["geo_third_region"] = geo["live"][2][0]
    F["geo_unmapped_pct"] = pct(geo["unmapped_share"] * 100)
    variants = []
    for key, label, colour, noun in (
        ("live", "Live companies", "navy", "companies"),
        ("insolvent", "Insolvencies", "red", "insolvencies"),
    ):
        rows = geo[key]
        xa, xmap = value_axis(None, max(n for _, n in rows), compact)
        variants.append({
            "key": key,
            "label": label,
            "spec": {
                "type": "bar",
                "data": {
                    "labels": [r[0] for r in rows],
                    "datasets": [bar_ds([r[1] for r in rows], PAL[colour],
                                        [f"{i(r[1])} {noun}" for r in rows])],
                },
                "options": {**base_options(index_axis="y"),
                            "scales": {"x": xa, "y": axis(grid=False)}},
                "tickLabels": {"x": xmap},
            },
        })
    C["c_geo"] = {"variants": variants}

    # ── the cycle ────────────────────────────────────────────────────────────
    crisis = max(complete[: len(complete) // 2], key=lambda r: r[1])
    recent = max(complete[len(complete) // 2:], key=lambda r: r[1])
    trough = min(complete[len(complete) // 2:], key=lambda r: r[1])
    F["cycle_crisis_year"] = str(crisis[0])
    F["cycle_crisis_value"] = approx(crisis[1])
    F["cycle_trough_year"] = str(trough[0])
    F["cycle_recent_year"] = str(recent[0])
    F["cycle_recent_value"] = approx(recent[1], 500)
    F["cycle_partial_year"] = str(last_notice.year)
    F["cycle_partial_month"] = month_name(last_notice)
    cyc_labels = [str(y) for y, _, _ in cyc]
    ya, ymap = value_axis("insolvencies", max(n for _, n, _ in cyc), compact)
    C["c_cycle"] = {
        "type": "line",
        "data": {
            "labels": cyc_labels,
            "datasets": [dict(line_ds("", [n for _, n, _ in cyc], "navy",
                                      [f"{i(n)} insolvencies" + (" (partial year)" if part else "")
                                       for _, n, part in cyc], fill=True),
                              pointBackgroundColor=[PAL["grey"] if part else PAL["navy"]
                                                    for _, _, part in cyc])],
        },
        "options": {**base_options(),
                    "scales": {"x": axis(grid=False, ticks={"maxTicksLimit": 14}), "y": ya}},
        "tickLabels": {"y": ymap},
        "bands": recession_bands(cyc_labels),
    }

    # ── composition of exit ──────────────────────────────────────────────────
    mix = b.exit_mix(gz_first, gz_last)
    lowest = min(mix, key=lambda r: r[1])
    F["exitmix_first_year"] = str(mix[0][0])
    F["exitmix_first_pct"] = pct(mix[0][1])
    F["exitmix_low_year"] = str(lowest[0])
    F["exitmix_low_pct"] = pct(lowest[1])
    F["exitmix_last_year"] = str(mix[-1][0])
    F["exitmix_last_pct"] = pct(mix[-1][1])
    ya, ymap = value_axis("% of dated exits insolvent", 100, lambda v: pctn(v, 0))
    C["c_exitmix"] = {
        "type": "line",
        "data": {"labels": [str(y) for y, _ in mix],
                 "datasets": [line_ds("insolvent %", [p for _, p in mix], "red",
                                      [f"{pctn(p, 0)} of exits insolvent" for _, p in mix],
                                      fill=True)]},
        "options": {**base_options(), "scales": {"x": axis(grid=False), "y": ya}},
        "tickLabels": {"y": ymap},
        "bands": recession_bands([str(y) for y, _ in mix]),
    }

    # ── size ─────────────────────────────────────────────────────────────────
    bands, unknown_pct = b.size_rates()
    for name, p in bands:
        F[f"size_pct_{name}"] = pct(p, 1)
    F["size_pct_unknown"] = pct(unknown_pct, 1)
    ya, ymap = value_axis("% ever insolvent", max(p for _, p in bands), lambda v: pctn(v, 0))
    C["c_size"] = {
        "type": "bar",
        "data": {"labels": [n.capitalize() for n, _ in bands],
                 "datasets": [bar_ds([p for _, p in bands], PAL["blue"],
                                     [f"{pctn(p)} insolvent" for _, p in bands])]},
        "options": {**base_options(), "scales": {"x": axis(grid=False), "y": ya}},
        "tickLabels": {"y": ymap},
    }

    # ── industry ─────────────────────────────────────────────────────────────
    ind, ind_median, ind_n = b.industry_rates()
    F["ind_top1_name"] = ind[0][0]
    F["ind_top1_pct"] = pct(ind[0][1], 1)
    F["ind_top2_name"] = ind[1][0]
    F["ind_top2_pct"] = pct(ind[1][1], 1)
    F["ind_median_pct"] = pct(ind_median, 1)
    F["ind_ratio"] = times_word(ind[0][1] / ind_median)
    F["ind_count"] = str(ind_n)
    F["ind_min_firms"] = i(MIN_INDUSTRY_FIRMS)
    xa, xmap = value_axis("% ever insolvent", max(p for _, p in ind), lambda v: pctn(v, 0))
    C["c_ind"] = {
        "type": "bar",
        "data": {"labels": [d for d, _ in ind],
                 "datasets": [bar_ds([p for _, p in ind], PAL["red"],
                                     [f"{pctn(p)} insolvent" for _, p in ind])]},
        "options": {**base_options(index_axis="y"),
                    "scales": {"x": xa, "y": axis(grid=False)}},
        "tickLabels": {"x": xmap},
    }

    # ── gross value added ────────────────────────────────────────────────────
    g = b.gva()
    F["gva_computable_pct"] = pct(g["computable_pct"], 2)
    F["gva_excluded"] = word(g["excluded"])
    F["gva_ceiling"] = f"£{round(GVA_CEILING / 1e9)}bn"
    return F, T, C, {
        "gz_first": gz_first, "gz_last": gz_last, "last_notice": last_notice,
        "birth_last": birth_last,
    }


def build_listed(b: Build, F: dict, T: dict, C: dict) -> None:
    """Part III — the listed-firm series (FTSE 100 and S&P 500)."""
    ftse_value_years = b.coverage_years(
        "ftse100_consolidated", "year", ["market_cap_gbp"], PARTIAL_YEAR_RATIO
    )
    last_ftse = max(ftse_value_years)

    # ── FTSE balanced value panel ────────────────────────────────────────────
    panel = b.ftse_value_panel(last_ftse)
    ser = panel["series"]
    base = panel["base"]
    idx = {y: ix for y, _, ix in ser}
    after_base = [y for y in idx if y > base]
    drop_year = min(after_base, key=lambda y: idx[y])
    F["panel_n"] = str(panel["n"])
    F["panel_start_year"] = str(panel["start"])
    F["panel_base_year"] = str(base)
    F["panel_drop_year"] = str(drop_year)
    F["panel_drop_pct"] = pct(100.0 - idx[drop_year])
    F["panel_last_year"] = str(ser[-1][0])
    F["panel_years_after"] = word(ser[-1][0] - base)
    F["panel_gap"] = gap_phrase(ser[-1][2])
    F["panel_base_value"] = gbp_tn(dict((y, v) for y, v, _ in ser)[base] / 1e12)
    ya, ymap = value_axis(f"index ({base} = 100)", max(ix for _, _, ix in ser),
                          lambda v: f"{v:g}")
    C["c_panel"] = {
        "type": "line",
        "data": {"labels": [str(y) for y, _, _ in ser],
                 "datasets": [line_ds(f"index ({base} = 100)", [round(ix, 1) for _, _, ix in ser],
                                      "navy",
                                      [f"index {ix:.1f} ({gbp_tn(v / 1e12)})" for _, v, ix in ser],
                                      fill=True)]},
        "options": {**base_options(), "scales": {"x": axis(grid=False), "y": ya}},
        "tickLabels": {"y": ymap},
        "bands": recession_bands([str(y) for y, _, _ in ser]),
    }

    # ── FTSE dividends ───────────────────────────────────────────────────────
    div = b.ftse_dividend_panel(last_ftse, base)
    dser = div["series"]
    dbase = div["base"]
    dvals = {y: bn for y, bn, _ in dser}
    didx = {y: ix for y, _, ix in dser}
    dtrough_year = min((y for y in didx if y > dbase), key=lambda y: didx[y])
    covid_year = min(
        (y for y in didx if y > dtrough_year + 5), key=lambda y: didx[y], default=dser[-1][0]
    )
    F["div_n"] = str(div["n"])
    F["div_base_year"] = str(dbase)
    F["div_base_total"] = gbp_bn(dvals[dbase])
    F["div_trough_year"] = str(dtrough_year)
    F["div_trough_phrase"] = change_phrase(dvals[dbase], dvals[dtrough_year])
    F["div_last_year"] = str(dser[-1][0])
    F["div_last_gap"] = gap_phrase(dser[-1][2])
    F["div_second_cut_year"] = str(covid_year)
    ya, ymap = value_axis(f"index ({dbase} = 100)", max(ix for _, _, ix in dser),
                          lambda v: f"{v:g}")
    C["c_div"] = {
        "type": "line",
        "data": {"labels": [str(y) for y, _, _ in dser],
                 "datasets": [line_ds(f"index ({dbase} = 100)", [round(ix) for _, _, ix in dser],
                                      "navy",
                                      [f"index {ix:.0f} ({gbp_bn(bn)})" for _, bn, ix in dser],
                                      fill=True)]},
        "options": {**base_options(), "scales": {"x": axis(grid=False), "y": ya}},
        "tickLabels": {"y": ymap},
        "bands": recession_bands([str(y) for y, _, _ in dser]),
    }

    # ── index turnover ───────────────────────────────────────────────────────
    # ── S&P earnings ─────────────────────────────────────────────────────────
    ni = b.sp_median_net_income()
    nid = dict(ni)
    ni_base = base if base in nid else ni[0][0]
    trough_year = min((y for y in nid if y > ni_base), key=lambda y: nid[y])
    F["earn_base_year"] = str(ni_base)
    F["earn_base"] = usd_m(nid[ni_base])
    F["earn_trough_year"] = str(trough_year)
    F["earn_trough"] = usd_m(nid[trough_year])
    F["earn_last_year"] = str(ni[-1][0])
    F["earn_last"] = usd_m(ni[-1][1])
    F["earn_crisis_phrase"] = change_phrase(nid[ni_base], nid[trough_year])
    F["earn_gap"] = gap_phrase(100.0 * ni[-1][1] / nid[ni_base])
    ya, ymap = value_axis("median net income ($m)", max(v for _, v in ni), lambda v: f"${v:,.0f}m")
    C["c_earn"] = {
        "type": "line",
        "data": {"labels": [str(y) for y, _ in ni],
                 "datasets": [line_ds("median net income", [round(v) for _, v in ni], "green",
                                      [f"median {usd_m(v)} per constituent" for _, v in ni],
                                      fill=True)]},
        "options": {**base_options(), "scales": {"x": axis(grid=False), "y": ya}},
        "tickLabels": {"y": ymap},
        "bands": recession_bands([str(y) for y, _ in ni]),
    }

    # ── sector composition of market value ───────────────────────────────────
    sectors = b.gics_sectors()
    sp_years, sp_dropped, dq_ceiling = b.usable_market_cap_years(
        "sp500_consolidated", "fiscal_year", "market_cap", "sp", PARTIAL_YEAR_RATIO
    )
    ftse_comp_years, ftse_dropped, _ = b.usable_market_cap_years(
        "ftse100_compositions", "year", "market_cap_gbp", "ftse", PARTIAL_YEAR_RATIO
    )
    sec_year = max(set(sp_years) & set(ftse_comp_years))
    F["dq_ceiling"] = pct(dq_ceiling)
    shares = b.sector_value_shares(sec_year, sectors)
    order = sorted(sectors, key=lambda s: shares["sp"].get(s, 0), reverse=True)
    tech = "Information Technology"
    it_series = b.sp_sector_share_series(tech)
    F["sec_year"] = str(sec_year)
    # How much of that year's index value is actually classified. Before the
    # EDGAR sector backfill this sat near 47% and nothing on the page said so.
    F["sec_coverage"] = pct(b.sp_sector_coverage(sec_year))
    F["sec_sp_it_pct"] = pct(shares["sp"].get(tech, 0))
    F["sec_ftse_it_pct"] = pct(shares["ftse"].get(tech, 0))
    ftse_order = sorted(sectors, key=lambda s: shares["ftse"].get(s, 0), reverse=True)
    F["sec_ftse_top1"] = ftse_order[0].lower()
    F["sec_ftse_top2"] = ftse_order[1].lower()
    F["sec_ftse_top3"] = ftse_order[2].lower()
    F["sec_it_first_year"] = str(it_series[0][0])
    F["sec_it_change"] = change_phrase(it_series[0][1], it_series[-1][1])
    xa, xmap = value_axis(f"share of index market value, {sec_year} (%)",
                          max(max(shares["sp"].values()), max(shares["ftse"].values())),
                          lambda v: pctn(v, 0))
    C["c_tech"] = {
        "type": "bar",
        "data": {
            "labels": order,
            "datasets": [
                bar_ds([round(shares["sp"].get(s, 0), 1) for s in order], PAL["blue"],
                       [f"S&P 500: {pctn(shares['sp'].get(s, 0))}" for s in order],
                       label="S&P 500", radius=3),
                bar_ds([round(shares["ftse"].get(s, 0), 1) for s in order], PAL["amber"],
                       [f"FTSE 100: {pctn(shares['ftse'].get(s, 0))}" for s in order],
                       label="FTSE 100", radius=3),
            ],
        },
        "options": {**base_options(legend=True, index_axis="y"),
                    "scales": {"x": xa, "y": axis(grid=False)}},
        "tickLabels": {"x": xmap},
    }

    # ── FTSE structure over time ─────────────────────────────────────────────
    memb = b.ftse_membership_sectors()
    myears = sorted(memb)
    first, last = myears[0], myears[-1]

    def share(y, s):
        return memb[y].get(s, 0.0)

    # Ties broken by end share, so a sector that ends large is drawn ahead of one
    # that moved the same distance from a small base.
    movers = sorted(sectors,
                    key=lambda s: (abs(share(last, s) - share(first, s)), share(last, s)),
                    reverse=True)
    drawn = [tech] + [s for s in movers if s != tech][:3]
    # Ties on the change are broken by the end share, so the sector reported is
    # the one that ends larger — Industrials and Communication Services both
    # rise by exactly five points across the record.
    faller = min(drawn, key=lambda s: (share(last, s) - share(first, s), -share(first, s)))
    riser = max(drawn, key=lambda s: (share(last, s) - share(first, s), share(last, s)))
    it_avg = sum(share(y, tech) for y in myears) / len(myears)
    F["fsec_first_year"] = str(first)
    F["fsec_last_year"] = str(last)
    F["fsec_it_avg"] = pct(it_avg)
    F["fsec_faller"] = faller.lower()
    F["fsec_faller_first"] = pct(share(first, faller))
    F["fsec_faller_last"] = pct(share(last, faller))
    F["fsec_riser"] = riser.lower()
    F["fsec_riser_first"] = pct(share(first, riser))
    F["fsec_riser_last"] = pct(share(last, riser))
    colours = ["blue", "green", "red", "amber"]
    ya, ymap = value_axis("% of index membership",
                          max(share(y, s) for y in myears for s in drawn), lambda v: pctn(v, 0))
    C["c_ftsesec"] = {
        "type": "line",
        "data": {
            "labels": [str(y) for y in myears],
            "datasets": [
                dict(line_ds(s, [share(y, s) for y in myears], colours[k % len(colours)],
                             [f"{s}: {pctn(share(y, s))}" for y in myears], point=0,
                             width=3 if s == tech else 2.5),
                     tension=0.35)
                for k, s in enumerate(drawn)
            ],
        },
        "options": {**base_options(legend=True, interaction_index=True),
                    "scales": {"x": axis(grid=False, ticks={"maxTicksLimit": 9}), "y": ya}},
        "tickLabels": {"y": ymap},
        "bands": recession_bands([str(y) for y in myears]),
    }

    # ── valuation gap ────────────────────────────────────────────────────────
    ta_years = b.coverage_years_min("ftse100_consolidated", "year",
                                    ["market_cap_gbp", "total_assets"],
                                    round(PARTIAL_YEAR_RATIO * INDEX_SIZE["ftse"]))
    vg_year = max(set(ta_years) & set(sp_years))
    vg = b.valuation_gap(vg_year)
    vg_shares = b.sector_value_shares(vg_year, sectors) if vg_year != sec_year else shares
    F["vg_year"] = str(vg_year)
    F["vg_sp_mb"] = times(vg["sp_mb"])
    F["vg_ftse_mb"] = times(vg["ftse_mb"])
    F["vg_sp_exfin"] = f"{vg['sp_mb_exfin']:.2f}x"
    F["vg_ftse_exfin"] = f"{vg['ftse_mb_exfin']:.2f}x"
    F["vg_ftse_n"] = str(vg["ftse_n"])
    F["vg_ftse_fund_year"] = str(vg["ftse_first_fundamentals_year"])
    F["vg_sp_it_pct"] = pct(vg_shares["sp"].get(tech, 0))
    F["vg_ftse_it_pct"] = pct(vg_shares["ftse"].get(tech, 0))
    ya, ymap = value_axis(f"market value ÷ book assets, {vg_year} (×)",
                          max(vg["sp_mb"], vg["ftse_mb"]),
                          lambda v: f"{v:g}×" if v else "0", count=4)
    C["c_vg"] = {
        "type": "bar",
        "data": {"labels": ["S&P 500", "FTSE 100"],
                 "datasets": [bar_ds([round(vg["sp_mb"], 2), round(vg["ftse_mb"], 2)],
                                     [PAL["blue"], PAL["amber"]],
                                     [f"Market-to-book: {vg['sp_mb']:.2f}×",
                                      f"Market-to-book: {vg['ftse_mb']:.2f}×"], radius=5)]},
        "options": {**base_options(), "scales": {"x": axis(grid=False), "y": ya}},
        "tickLabels": {"y": ymap},
    }

    # ── concentration ────────────────────────────────────────────────────────
    conc = b.concentration()
    sp_c, ftse_c = conc["sp"], conc["ftse"]
    F["conc_sp_first_year"] = str(sp_c[0][0])
    F["conc_sp_first_pct"] = pct(sp_c[0][1])
    F["conc_sp_last_year"] = str(sp_c[-1][0])
    F["conc_sp_last_pct"] = pct(sp_c[-1][1])
    F["conc_ftse_avg_pct"] = pct(sum(p for _, p in ftse_c) / len(ftse_c))
    F["conc_ftse_first_year"] = str(ftse_c[0][0])
    F["conc_ftse_last_year"] = str(ftse_c[-1][0])
    F["dq_dropped_years"] = ", ".join(str(y) for y in conc["dropped"]) if conc["dropped"] else "none"
    F["dq_dropped_count"] = word(len(conc["dropped"]))
    ya, ymap = value_axis("top-10 share of index value (%)",
                          max(p for _, p in sp_c + ftse_c), lambda v: pctn(v, 0))
    conc_years = [y for y, _ in sp_c + ftse_c]
    x_first, x_last = min(conc_years), max(conc_years)
    xmap = {str(y): str(y) for y in range(x_first - 1, x_last + 2)}
    C["c_conc"] = {
        "type": "line",
        "data": {"datasets": [
            dict(line_ds("S&P 500 top-10", [{"x": y, "y": round(p, 1)} for y, p in sp_c], "blue",
                         [f"S&P 500 top-10: {pctn(p)}" for _, p in sp_c])),
            dict(line_ds("FTSE 100 top-10", [{"x": y, "y": round(p, 1)} for y, p in ftse_c], "amber",
                         [f"FTSE 100 top-10: {pctn(p)}" for _, p in ftse_c])),
        ]},
        "options": {**base_options(legend=True), "parsing": False,
                    "scales": {"x": dict(axis(grid=False, ticks={"stepSize": 2}),
                                         type="linear", min=x_first - 1, max=x_last + 1),
                               "y": ya}},
        "tickLabels": {"y": ymap, "x": xmap},
        "bands": linear_bands(x_first - 1, x_last + 1),
    }

    # ── forthcoming: the death record ────────────────────────────────────────
    ch = b.ch_extraction()
    gap = b.rows(
        "select count(*), count(c.\"CompanyNumber\") from exit_events e "
        "left join companies c on c.\"CompanyNumber\" = e.company_number_norm"
    )[0]
    F["snapshot_missing_pct"] = pct(100.0 * (gap[0] - gap[1]) / gap[0], 1)
    F["ch_profiles"] = i(ch["profiles"])
    F["ch_dissolved"] = i(ch["dissolved"])


# ─────────────────────────────────────────────────────────────────────────────
# Wiring gate — the HTML may only reference keys this build actually produced,
# and every spec produced must be consumed by a canvas.
# ─────────────────────────────────────────────────────────────────────────────

# Digits that are part of a proper name or a citation, not a computed figure.
ALLOWED_LITERALS = [
    "FTSE 100", "FTSE&nbsp;100", "S&P 500", "S&amp;P&nbsp;500", "S&amp;P 500",
    "Becker, Benmelech and Monteiro (2026)",
    "ITL3", "NUTS3",
]


def verify(payload: dict, html_path: Path) -> int:
    html = html_path.read_text()
    problems: list[str] = []

    refs = set(re.findall(r'data-f="([^"]+)"', html))
    texts = set(re.findall(r'data-t="([^"]+)"', html))
    canvases = set(re.findall(r'<canvas id="([^"]+)"', html))

    missing = sorted(refs - set(payload["figures"]))
    if missing:
        problems.append(f"HTML references {len(missing)} unknown figure(s): {missing}")
    missing_t = sorted(texts - set(payload["text"]))
    if missing_t:
        problems.append(f"HTML references {len(missing_t)} unknown text key(s): {missing_t}")

    unused = sorted(set(payload["figures"]) - refs)
    if unused:
        problems.append(f"{len(unused)} computed figure(s) unused by the HTML: {unused}")
    unused_t = sorted(set(payload["text"]) - texts)
    if unused_t:
        problems.append(f"{len(unused_t)} computed text key(s) unused: {unused_t}")

    # every map the page asks for must exist, and every map built must be used
    maps_in_html = set(re.findall(r'data-map="([^"]+)"', html))
    data_dir = html_path.parent / "data"
    for name in sorted(maps_in_html):
        if not (data_dir / name).exists():
            problems.append(f"HTML references a map that was not built: {name}")
    built_maps = {f.name for f in data_dir.glob("map_*.json")}
    orphan_maps = sorted(built_maps - maps_in_html)
    if orphan_maps:
        problems.append(f"Map file(s) built but never shown: {orphan_maps}")

    missing_charts = sorted(canvases - set(payload["charts"]))
    if missing_charts:
        problems.append(f"Canvas without a chart spec: {missing_charts}")
    unused_charts = sorted(set(payload["charts"]) - canvases)
    if unused_charts:
        problems.append(f"Chart spec without a canvas: {unused_charts}")

    # No number may survive as a literal in the prose.
    body = re.sub(r"<style.*?</style>|<script.*?</script>", "", html, flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    for allowed in ALLOWED_LITERALS:
        body = body.replace(allowed, " ")
    literals = sorted(set(re.findall(r"\d[\d,.]*", body)))
    if literals:
        problems.append(f"Hardcoded number(s) left in prose: {literals}")

    for name, problem in enumerate(problems, 1):
        print(f"  ✗ {problem}")
    if not problems:
        print(
            f"  ✓ {len(refs)} figures, {len(texts)} labels, {len(canvases)} charts, "
            f"{len(maps_in_html)} maps all resolve; no hardcoded numbers in prose"
        )
    return len(problems)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verify", action="store_true", help="check the HTML's wiring after building")
    ap.add_argument("--out", default=str(OUT), help=f"output path (default {OUT})")
    args = ap.parse_args()

    db = resolve_db()
    con = duckdb.connect(str(db), read_only=True)
    b = Build(con)

    F, T, C, ctx = build_population(b)
    build_listed(b, F, T, C)
    build_lifecycle(b, F, T, C, ctx)
    maps = build_geography(con, F, T)

    db_built, db_note = con.execute("select built_at, note from _build_info limit 1").fetchone()
    payload = {
        "meta": {
            "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "database": db.name,
            "database_built_at": db_built.isoformat(timespec="seconds"),
            "database_note": db_note,
            "latest_notice": ctx["last_notice"].isoformat(),
            "complete_years": {
                "gazette": [ctx["gz_first"], ctx["gz_last"]],
                "incorporations_to": ctx["birth_last"],
            },
            "generator": "python/build_site_data.py",
        },
        "figures": F,
        "text": T,
        "charts": C,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"wrote {out.relative_to(REPO)}  ({out.stat().st_size / 1024:.0f} KB)")
    print(f"  {len(F)} figures · {len(T)} labels · {len(C)} charts · db {db.name}")
    for level, size in maps.items():
        print(f"  map_{level}.json: {size / 1e6:.2f} MB")

    if args.verify:
        if not HTML.exists():
            print(f"  ✗ {HTML} not found")
            return 1
        return 1 if verify(payload, HTML) else 0
    return 0



# ─────────────────────────────────────────────────────────────────────────────
# Choropleth maps.
#
# The back end joins company postcodes to ONS geography, aggregates per area,
# projects the boundary polygons (already in British National Grid) straight to
# SVG path strings, assigns a colour per area from quantile bins, and writes one
# file per map. The front end appends <path> elements and draws a legend; it
# performs no projection, no binning and no arithmetic.
#
# Cached inputs come from python/fetch_ons_geography.py (Open Government Licence
# v3.0 — the attribution below is rendered on the page).
# ─────────────────────────────────────────────────────────────────────────────

# The FTSE sector classification lives in the repository, not in the database.
# It previously existed only as a DuckDB table and was lost when that file was
# deleted; a committed CSV cannot be lost the same way.
FTSE_SECTORS = REPO / "source_inputs" / "ftse100_sector_classification.csv"
# Same classification, resolved to company_number by build_ftse_sector_crosswalk.py.
# Tickers are reused in London, so company_number is the only safe join key.
FTSE_SECTORS_KEYED = REPO / "source_inputs" / "ftse100_sector_classification_keyed.csv"

ONS_CACHE = REPO / "source_inputs" / "ons"
PC_LOOKUP = ONS_CACHE / "postcode_lookup.parquet"
LAD_TO_ITL3 = ONS_CACHE / "lad_to_itl3.json"
POPULATION = ONS_CACHE / "population_lad.csv"
OGL_ATTRIBUTION = (
    "Boundaries and postcode geography: Office for National Statistics, "
    "licensed under the Open Government Licence v3.0. Contains OS data "
    "&copy; Crown copyright and database right 2026."
)

# A full UK postcode, as printed in a Gazette notice.
PC_FULL_IN_TEXT = r"regexp_extract(upper(notice_text),'[A-Z]{1,2}[0-9][0-9A-Z]?\s+[0-9][A-Z]{2}',0)"

MAP_WIDTH = 640          # SVG user units across the widest map
MAP_BINS = 6             # quantile classes per choropleth
MIN_FIRMS_FOR_GVA = 50   # suppress an area's median below this many firm-years
MIN_FIRMS_FOR_RATE = 100  # suppress a failure share below this many observed firms
HEAT_COLUMNS = 150        # grid columns across the density surface (~4.5 km cells)
MIN_PER_CAPITA_POP = 1000 # a per-capita rate needs a real population behind it

# Sequential ramps built from the site's own tokens (light → saturated).
RAMPS = {
    "navy": ["#e8ecf3", "#c3cfe0", "#93a8c6", "#6580ab", "#3d5b8e", "#1f3864"],
    "red": ["#f7e7e3", "#eec6bd", "#df9d8f", "#cd7460", "#bb573f", "#8f2f1c"],
    "teal": ["#e4efee", "#c0dcd8", "#93c4be", "#63a9a1", "#3a8e85", "#1d6b62"],
    "amber": ["#faf1e0", "#f0dcb4", "#e2c081", "#d1a250", "#b9862a", "#8c6410"],
}
NO_DATA_COLOUR = "#eceae4"


def _polygons(geometry: dict) -> list[list[list[float]]]:
    """Every ring of a Polygon / MultiPolygon, as lists of [x, y] pairs."""
    kind, coords = geometry["type"], geometry["coordinates"]
    if kind == "Polygon":
        return coords
    if kind == "MultiPolygon":
        return [ring for poly in coords for ring in poly]
    return []


def mercator(lon: float, lat: float) -> tuple[float, float]:
    """Spherical Mercator. Boundaries arrive in WGS84 because British National
    Grid covers Great Britain only — Northern Ireland comes back in Irish Grid
    and would land on Wales."""
    return lon, math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _svg_path(rings, ox, oy, scale, height) -> str:
    """Project WGS84 rings through Mercator into one SVG path string.

    Coordinates are rounded to whole user units (roughly a kilometre at the
    published width), which both simplifies the outline and keeps the payload
    small. Rings that collapse to fewer than three distinct points are dropped.
    """
    parts = []
    for ring in rings:
        pts = []
        last = None
        for lon, lat in ring:
            x, y = mercator(lon, lat)
            px = round((x - ox) * scale)
            py = round(height - (y - oy) * scale)
            if (px, py) != last:
                pts.append((px, py))
                last = (px, py)
        if len(pts) < 3:
            continue
        parts.append("M" + "L".join(f"{px} {py}" for px, py in pts) + "Z")
    return "".join(parts)


def _bins(values: list[float], ramp: str, fmt) -> tuple[list[dict], callable]:
    """Quantile classes plus a value → colour function."""
    ordered = sorted(values)
    colours = RAMPS[ramp]
    n = len(colours)
    edges = [ordered[min(len(ordered) - 1, round(len(ordered) * k / n))] for k in range(1, n)]

    def colour_of(v):
        if v is None:
            return NO_DATA_COLOUR
        for k, edge in enumerate(edges):
            if v < edge:
                return colours[k]
        return colours[-1]

    legend = []
    lo = ordered[0]
    for k, edge in enumerate(edges):
        legend.append({"color": colours[k], "label": f"{fmt(lo)} – {fmt(edge)}"})
        lo = edge
    legend.append({"color": colours[-1], "label": f"{fmt(lo)} – {fmt(ordered[-1])}"})
    return legend, colour_of


def render_heat(grid: dict, fmt, legend_title: str) -> dict:
    """Project the density grid to SVG rectangles, one colour per quantile."""
    minx, miny, maxx, maxy = grid["bounds"]
    cell = grid["cell"]
    scale = MAP_WIDTH / (maxx - minx)
    height = round((maxy - miny) * scale)
    size = cell * scale
    counts = [n for _, _, n in grid["cells"]]
    legend, colour_of = _bins(counts, "navy", fmt)
    return {
        "viewBox": f"0 0 {MAP_WIDTH} {height}",
        "attribution": OGL_ATTRIBUTION,
        # A hair of overlap closes sub-pixel seams between adjacent cells without
        # filling genuinely empty rows, which stay visible as gaps.
        "cellSize": round(size + 0.35, 3),
        "legendTitle": legend_title,
        "legend": legend,
        "cells": [
            {
                "x": round(gx * size, 1),
                "y": round(height - (gy + 1) * size, 1),
                "fill": colour_of(n),
                "title": f"{i(n)} companies registered in this cell",
            }
            for gx, gy, n in grid["cells"]
        ],
    }


class Maps:
    """Builds every choropleth from the postcode lookup and ONS boundaries."""

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.con = con
        if not PC_LOOKUP.exists():
            sys.exit(
                f"Missing {PC_LOOKUP.relative_to(REPO)}.\n"
                "Run: ./venv/bin/python python/fetch_ons_geography.py"
            )
        self.con.execute(
            f"create or replace temp view pc as select * from '{PC_LOOKUP}'"
        )
        # live register: company -> area
        self.con.execute(
            """create or replace temp view company_area as
               select c."CompanyNumber" as cn, pc.lad, pc.msoa
               from companies c
               join pc on pc.pc = upper(replace(c."RegAddress_PostCode", ' ', ''))"""
        )
        # insolvent exits: the registered office printed in the Gazette notice
        self.con.execute(
            f"""create or replace temp view insolvency_area as
                with n as (
                  select company_number,
                         -- min(), not any_value(): deterministic pick per company
                         min(upper(replace({PC_FULL_IN_TEXT}, ' ', ''))) as pc_norm
                  from gazette_events where company_number is not null group by 1)
                select pc.lad, pc.msoa
                from exit_events e
                join n on n.company_number = e.company_number_norm
                join pc on pc.pc = n.pc_norm
                where e.exit_class = 'insolvent'"""
        )

    def rows(self, sql: str) -> list[tuple]:
        return self.con.execute(sql).fetchall()

    # -- aggregates ----------------------------------------------------------
    def counts(self, level: str) -> dict[str, int]:
        return {
            a: n for a, n in self.rows(
                f"select {level}, count(*) from company_area where {level} is not null group by 1"
            )
        }

    def insolvencies(self, level: str) -> dict[str, int]:
        return {
            a: n for a, n in self.rows(
                f"select {level}, count(*) from insolvency_area where {level} is not null group by 1"
            )
        }

    def gva(self, level: str) -> tuple[dict[str, float], dict[str, float]]:
        """Total value added, and the median per employee.

        A median *per firm-year* is not published: only large filers submit a full
        profit-and-loss, so that measure is near-flat everywhere and reports how
        big the big filers are rather than anything about the area. Total value
        added and value added per employee both carry real signal.
        """
        total = {
            a: float(v) for a, v, _ in self.rows(
                f"""select ca.{level}, sum(f.staff_costs + f.operating_profit), count(*)
                    from combined_firm_year f
                    join company_area ca on ca.cn = f.company_number
                    where coalesce(f.filing_suspect, false) = false
                      and f.staff_costs is not null and f.operating_profit is not null
                      and abs(f.staff_costs) < 10e9 and abs(f.operating_profit) < 10e9
                      and ca.{level} is not null
                    group by 1 having count(*) >= {MIN_FIRMS_FOR_GVA}"""
            )
        }
        per_employee = {
            a: float(v) for a, v, _ in self.rows(
                f"""select ca.{level},
                           median((f.staff_costs + f.operating_profit) / f.employees),
                           count(*)
                    from combined_firm_year f
                    join company_area ca on ca.cn = f.company_number
                    where coalesce(f.filing_suspect, false) = false
                      and f.staff_costs is not null and f.operating_profit is not null
                      and abs(f.staff_costs) < 10e9 and abs(f.operating_profit) < 10e9
                      and f.employees > 0 and ca.{level} is not null
                    group by 1 having count(*) >= {MIN_FIRMS_FOR_GVA}"""
            )
        }
        return total, per_employee

    def population(self) -> dict[str, float]:
        """Mid-year population estimate per local authority. Northern Ireland
        returns no value in the Nomis series, so those districts are absent and
        are left unshaded on per-capita maps rather than estimated."""
        rows = self.rows(
            f"select column0, try_cast(column2 as double) from read_csv_auto('{POPULATION}', "
            "header=false, skip=1, all_varchar=true)"
        )
        return {code: pop for code, pop in rows if pop and pop >= MIN_PER_CAPITA_POP}

    @staticmethod
    def lad_to_itl3() -> dict[str, dict]:
        return json.loads(LAD_TO_ITL3.read_text())

    @staticmethod
    def to_itl3(by_lad: dict[str, float], mapping: dict[str, dict]) -> dict[str, float]:
        """Sum a local-authority measure up to ITL3, the geography that replaced
        NUTS3 — a coarser unit, so small dense authorities are not compared
        against sprawling rural ones."""
        out: dict[str, float] = {}
        for lad, value in by_lad.items():
            area = mapping.get(lad)
            if area:
                out[area["code"]] = out.get(area["code"], 0) + value
        return out

    def heat_grid(self, columns: int = HEAT_COLUMNS) -> dict:
        """Registered companies per grid cell, from postcode coordinates.

        A choropleth's colour is driven partly by the size of the boundary it
        fills, which flatters large rural authorities and dilutes dense small
        ones. A fixed grid removes that: every cell is the same size on the
        ground, so the pattern comes from where companies actually are.
        """
        bounds = self.rows(
            "select min(lon), max(lon), min(mercator_y), max(mercator_y) from ("
            "  select pc.lon as lon,"
            "         degrees(ln(tan(pi()/4 + radians(pc.lat)/2))) as mercator_y"
            "  from companies c join pc on pc.pc = upper(replace(c.\"RegAddress_PostCode\", ' ', ''))"
            "  where pc.lat is not null and pc.lat between 49 and 61 and pc.lon between -9 and 2)"
        )[0]
        minx, maxx, miny, maxy = (float(v) for v in bounds)
        cell = (maxx - minx) / columns
        rows = self.rows(
            f"""select floor((pc.lon - {minx}) / {cell})::int as gx,
                       floor((degrees(ln(tan(pi()/4 + radians(pc.lat)/2))) - {miny}) / {cell})::int as gy,
                       count(*) as n
                from companies c
                join pc on pc.pc = upper(replace(c."RegAddress_PostCode", ' ', ''))
                where pc.lat is not null and pc.lat between 49 and 61
                  and pc.lon between -9 and 2
                group by 1, 2
                -- ordered so the rendered cell array, and the file's bytes,
                -- are identical between runs
                order by 1, 2"""
        )
        return {
            "cells": [(int(gx), int(gy), int(n)) for gx, gy, n in rows],
            "bounds": (minx, miny, maxx, maxy),
            "cell": cell,
            "columns": columns,
        }

    def match_rate(self) -> float:
        matched, total = self.rows(
            """select (select count(*) from company_area),
                      (select count(*) from companies)"""
        )[0]
        return 100.0 * matched / total

    # -- rendering -----------------------------------------------------------
    @staticmethod
    def geometry(path: Path, code_field: str, name_field: str):
        data = json.loads(path.read_text())
        areas = []
        minx = miny = float("inf")
        maxx = maxy = float("-inf")
        for feat in data["features"]:
            rings = _polygons(feat["geometry"])
            if not rings:
                continue
            for ring in rings:
                for lon, lat in ring:
                    x, y = mercator(lon, lat)
                    minx, maxx = min(minx, x), max(maxx, x)
                    miny, maxy = min(miny, y), max(maxy, y)
            areas.append(
                {
                    "code": feat["properties"][code_field],
                    "name": feat["properties"][name_field],
                    "rings": rings,
                }
            )
        return areas, (minx, miny, maxx, maxy)

    def render(self, areas, bbox, variants: list[dict]) -> dict:
        minx, miny, maxx, maxy = bbox
        scale = MAP_WIDTH / (maxx - minx)
        height = round((maxy - miny) * scale)
        paths = {a["code"]: _svg_path(a["rings"], minx, miny, scale, height) for a in areas}
        names = {a["code"]: a["name"] for a in areas}
        order = [c for c in paths if paths[c]]
        out_variants = []
        for v in variants:
            values = v["values"]
            legend, colour_of = _bins([x for x in values.values() if x is not None],
                                      v["ramp"], v["fmt"])
            out_variants.append(
                {
                    "key": v["key"],
                    "label": v["label"],
                    "legendTitle": v["legend_title"],
                    "legend": legend,
                    "noDataColor": NO_DATA_COLOUR,
                    "noDataLabel": v["no_data_label"],
                    # index-aligned with `shapes` below, so an outline is stored once
                    "fills": [colour_of(values.get(c)) for c in order],
                    "titles": [
                        f"{names[c]} — {v['fmt'](values[c])} {v['unit']}"
                        if values.get(c) is not None
                        else f"{names[c]} — {v['no_data_label']}"
                        for c in order
                    ],
                }
            )
        return {
            "viewBox": f"0 0 {MAP_WIDTH} {height}",
            "attribution": OGL_ATTRIBUTION,
            "shapes": [paths[c] for c in order],
            "variants": out_variants,
        }


def build_geography(con: duckdb.DuckDBPyConnection, F: dict, T: dict) -> dict:
    """Writes the choropleth files and returns the prose figures they support."""
    m = Maps(con)
    written = {}

    lad_areas, lad_bbox = m.geometry(ONS_CACHE / "boundaries_lad.geojson", "LAD25CD", "LAD25NM")
    msoa_areas, msoa_bbox = m.geometry(ONS_CACHE / "boundaries_msoa.geojson", "MSOA21CD", "MSOA21NM")
    itl_areas, itl_bbox = m.geometry(ONS_CACHE / "boundaries_itl3.geojson", "ITL325CD", "ITL325NM")
    population = m.population()
    itl_map = m.lad_to_itl3()

    for level, areas, bbox, out_name in (
        ("lad", lad_areas, lad_bbox, "map_lad.json"),
        ("msoa", msoa_areas, msoa_bbox, "map_msoa.json"),
    ):
        companies = m.counts(level)
        insolvencies = m.insolvencies(level)
        # Share of the firms ever observed at an address in this area that ended
        # in insolvency. Bounded by construction, unlike historical insolvencies
        # divided by a present-day register count.
        rates = {
            a: 100.0 * insolvencies.get(a, 0) / (n + insolvencies.get(a, 0))
            for a, n in companies.items()
            if n + insolvencies.get(a, 0) >= MIN_FIRMS_FOR_RATE
        }
        variants = [
            {
                "key": "companies", "label": "Companies", "ramp": "navy",
                "values": companies, "fmt": i, "unit": "companies",
                "legend_title": "companies on the register",
                "no_data_label": "no companies matched",
            },
            {
                "key": "insolvency", "label": "Insolvency share", "ramp": "red",
                "values": rates, "fmt": lambda v: pctn(v, 1),
                "unit": "of observed firms ended in insolvency",
                "legend_title": "share of observed firms that ended in insolvency",
                "no_data_label": f"fewer than {MIN_FIRMS_FOR_RATE} observed firms",
            },
        ]
        if level == "lad":
            per_capita = {
                a: 1000.0 * n / population[a]
                for a, n in companies.items() if a in population
            }
            variants.append(
                {
                    "key": "per_capita", "label": "Per 1,000 residents", "ramp": "teal",
                    "values": per_capita, "fmt": lambda v: f"{v:,.0f}",
                    "unit": "companies per 1,000 residents",
                    "legend_title": "companies per 1,000 residents",
                    "no_data_label": "no population estimate",
                }
            )
            names_lad = {a["code"]: a["name"] for a in areas}
            top_pc = max(per_capita.items(), key=lambda kv: kv[1])
            F["map_pc_top_name"] = names_lad[top_pc[0]]
            F["map_pc_top_value"] = f"{top_pc[1]:,.0f}"
            F["map_pc_median"] = f"{sorted(per_capita.values())[len(per_capita) // 2]:,.0f}"
            F["map_pc_areas"] = str(len(per_capita))
            F["map_pc_missing"] = str(len(companies) - len(per_capita))

        spec = m.render(areas, bbox, variants)
        path = REPO / "vercel_site" / "data" / out_name
        path.write_text(json.dumps(spec, separators=(",", ":"), ensure_ascii=False))
        written[level] = path.stat().st_size

        names = {a["code"]: a["name"] for a in areas}
        top_c = max(companies.items(), key=lambda kv: kv[1])
        top_r = max(rates.items(), key=lambda kv: kv[1])
        F[f"map_{level}_areas"] = i(len(areas))
        F[f"map_{level}_top_name"] = names[top_c[0]]
        F[f"map_{level}_top_value"] = i(top_c[1])
        F[f"map_{level}_worst_name"] = names[top_r[0]]
        F[f"map_{level}_worst_rate"] = pct(top_r[1], 1)

    # ITL3 — the geography that replaced NUTS3. Coarser than a local authority,
    # so a dense London borough is not set against a sprawling rural district.
    lad_companies = m.counts("lad")
    itl_companies = m.to_itl3(lad_companies, itl_map)
    itl_population = m.to_itl3({k: v for k, v in population.items()}, itl_map)
    itl_per_capita = {
        a: 1000.0 * n / itl_population[a]
        for a, n in itl_companies.items()
        if itl_population.get(a, 0) >= MIN_PER_CAPITA_POP
    }
    itl_names = {a["code"]: a["name"] for a in itl_areas}
    itl_spec = m.render(
        itl_areas, itl_bbox,
        [
            {
                "key": "companies", "label": "Companies", "ramp": "navy",
                "values": itl_companies, "fmt": i, "unit": "companies",
                "legend_title": "companies on the register",
                "no_data_label": "no companies matched",
            },
            {
                "key": "per_capita", "label": "Per 1,000 residents", "ramp": "teal",
                "values": itl_per_capita, "fmt": lambda v: f"{v:,.0f}",
                "unit": "companies per 1,000 residents",
                "legend_title": "companies per 1,000 residents",
                "no_data_label": "no population estimate",
            },
        ],
    )
    itl_path = REPO / "vercel_site" / "data" / "map_itl3.json"
    itl_path.write_text(json.dumps(itl_spec, separators=(",", ":"), ensure_ascii=False))
    written["itl3"] = itl_path.stat().st_size
    top_itl = max(itl_companies.items(), key=lambda kv: kv[1])
    top_itl_pc = max(itl_per_capita.items(), key=lambda kv: kv[1])
    F["map_itl_areas"] = str(len(itl_areas))
    F["map_itl_top_name"] = itl_names[top_itl[0]]
    F["map_itl_top_value"] = i(top_itl[1])
    F["map_itl_pc_top_name"] = itl_names[top_itl_pc[0]]
    F["map_itl_pc_top_value"] = f"{top_itl_pc[1]:,.0f}"

    # The density surface: fixed-size cells, so boundary size cannot colour it.
    grid = m.heat_grid()
    heat = render_heat(grid, i, "companies registered per grid cell")
    heat_path = REPO / "vercel_site" / "data" / "map_heat.json"
    heat_path.write_text(json.dumps(heat, separators=(",", ":"), ensure_ascii=False))
    written["heat"] = heat_path.stat().st_size
    busiest = max(grid["cells"], key=lambda c: c[2])
    km = grid["cell"] * 111.32 * math.cos(math.radians(54.5))
    F["heat_cells"] = i(len(grid["cells"]))
    F["heat_cell_km"] = f"{km:.0f} km"
    F["heat_max"] = i(busiest[2])
    F["heat_top_decile_share"] = pct(
        100.0 * sum(sorted((n for _, _, n in grid["cells"]), reverse=True)[: max(1, len(grid["cells"]) // 10)])
        / sum(n for _, _, n in grid["cells"])
    )

    # Gross value added has its own map: it rests on the minority of firms that
    # file a full profit-and-loss, so it needs its own caption and its own scale.
    gva_total, gva_per_emp = m.gva("lad")
    gva_per_head = {
        a: v / population[a] for a, v in gva_total.items()
        if a in population and v > 0
    }
    names = {a["code"]: a["name"] for a in lad_areas}
    thin = f"fewer than {MIN_FIRMS_FOR_GVA} firm-years with a full profit-and-loss"
    gva_spec = m.render(
        lad_areas, lad_bbox,
        [
            {
                "key": "total", "label": "Total value added", "ramp": "teal",
                "values": gva_total, "fmt": lambda v: gbp_bn(v / 1e9),
                "unit": "of measured value added",
                "legend_title": "total value added, all years",
                "no_data_label": thin,
            },
            {
                "key": "per_head", "label": "Per resident", "ramp": "amber",
                "values": gva_per_head, "fmt": lambda v: f"£{round(v):,}",
                "unit": "of measured value added per resident",
                "legend_title": "value added per resident",
                "no_data_label": "no population estimate",
            },
            {
                "key": "per_employee", "label": "Per employee", "ramp": "navy",
                "values": gva_per_emp, "fmt": lambda v: f"£{round(v / 1000):,}k",
                "unit": "median value added per employee",
                "legend_title": "median value added per employee",
                "no_data_label": thin,
            },
        ],
    )
    gva_path = REPO / "vercel_site" / "data" / "map_gva.json"
    gva_path.write_text(json.dumps(gva_spec, separators=(",", ":"), ensure_ascii=False))
    written["gva"] = gva_path.stat().st_size
    top_total = max(gva_total.items(), key=lambda kv: kv[1])
    runner = sorted(gva_total.items(), key=lambda kv: -kv[1])[1]
    top_emp = max(gva_per_emp.items(), key=lambda kv: kv[1])
    F["map_gva_top_name"] = names[top_total[0]]
    F["map_gva_top_value"] = gbp_bn(top_total[1] / 1e9)
    F["map_gva_second_name"] = names[runner[0]]
    F["map_gva_second_value"] = gbp_bn(runner[1] / 1e9)
    top_head = max(gva_per_head.items(), key=lambda kv: kv[1])
    F["map_gva_head_name"] = names[top_head[0]]
    F["map_gva_head_value"] = f"£{round(top_head[1]):,}"
    F["map_gva_prod_name"] = names[top_emp[0]]
    F["map_gva_prod_value"] = f"£{round(top_emp[1] / 1000):,}k"
    F["map_gva_areas"] = str(len(gva_total))
    F["map_gva_min_firms"] = str(MIN_FIRMS_FOR_GVA)
    F["map_match_pct"] = pct(m.match_rate())
    msoa_share = con.execute(
        """select 100.0 * count(*) filter(where msoa like 'E02%' or msoa like 'W02%')
                  / count(*) from company_area"""
    ).fetchone()[0]
    F["map_msoa_company_pct"] = pct(float(msoa_share))
    T["map_attribution"] = OGL_ATTRIBUTION
    return written


# ─────────────────────────────────────────────────────────────────────────────
# Lifecycle analysis: survival curves, the age-specific hazard, young-firm
# failure by calendar year, and entry rates. Added after the August 2026
# visualisations review.
# ─────────────────────────────────────────────────────────────────────────────

def _touched_years(start: float, end: float) -> tuple[int, int]:
    """The calendar years a recession falls in. 2008 Q2 - 2009 Q2 touches 2008
    and 2009."""
    return int(start), int(end) if end != int(end) else int(end) - 1


def recession_bands(labels: list[str]) -> list[dict]:
    """Recession spans in a category axis's index space.

    Each tick on these charts is one annual observation, so a band is drawn
    around the markers for the years the recession fell in — half a category
    either side — rather than at the exact quarter boundaries. Drawing 2008.25
    literally puts the band's left edge past the 2008 marker, leaving the year
    that entered the recession outside its own shading.
    """
    years = [int(t) for t in labels]
    first, last = years[0], years[-1]
    bands = []
    for start, end, label in RECESSIONS:
        y0, y1 = _touched_years(start, end)
        if y1 < first or y0 > last:
            continue
        bands.append(
            {
                "x0": round(max(y0, first) - first - 0.5, 3),
                "x1": round(min(y1, last) - first + 0.5, 3),
                "label": label,
            }
        )
    return bands


def linear_bands(first: int, last: int) -> list[dict]:
    """The same spans for an axis whose values are years."""
    out = []
    for start, end, label in RECESSIONS:
        y0, y1 = _touched_years(start, end)
        if y1 < first or y0 > last:
            continue
        out.append({"x0": max(y0 - 0.5, first), "x1": min(y1 + 0.5, last), "label": label})
    return out


class Lifecycle:
    """Survival, hazard and entry measures over the firm population."""

    def __init__(self, con: duckdb.DuckDBPyConnection, first_year: int, last_year: int):
        self.con = con
        self.first = first_year
        self.last = last_year

    def rows(self, sql: str) -> list[tuple]:
        return self.con.execute(sql).fetchall()

    def cohort_bands(self) -> list[dict]:
        """Birth-year bands drawn around the recessions, so each curve is a
        cohort that met a different macroeconomic environment."""
        crisis = next((r for r in RECESSIONS if r[0] > 2000), None)
        c0, c1 = int(crisis[0]), int(crisis[1])
        pandemic = next((r for r in RECESSIONS if r[0] >= 2020), None)
        p0 = int(pandemic[0])
        newest = self.last - MIN_OBSERVED_AGE   # a curve needs some years of follow-up
        spans = [
            (self.first, c0 - 1, "pre-crisis"),
            (c0, c1, "into the crisis"),
            (c1 + 1, p0 - 1, "recovery"),
            (p0, newest, "pandemic onward"),
        ]
        out = []
        for a, b, tag in spans:
            b = min(b, newest)
            if a <= b:
                out.append({"y0": a, "y1": b, "label": f"born {a}–{b} ({tag})"})
        return out

    def survival(self, y0: int, y1: int, insolvent_only: bool) -> list[float]:
        """Kaplan-Meier survival by age for one birth-year band.

        Censoring is administrative: a firm born in year b is observed for
        (last complete year - b) years. The curve stops at the oldest age the
        whole band has been observed to reach.
        """
        event = "exit_class = 'insolvent'" if insolvent_only else "death_date is not null"
        windows = dict(
            self.rows(
                f"select {self.last} - birth_year as w, count(*) from firm_master "
                f"where birth_year between {y0} and {y1} group by 1"
            )
        )
        deaths = dict(
            self.rows(
                f"""select extract(year from death_date)::int - birth_year as age, count(*)
                    from firm_master
                    where birth_year between {y0} and {y1} and {event}
                      and death_date is not null
                      and extract(year from death_date)::int - birth_year >= 0
                    group by 1"""
            )
        )
        max_age = min(windows) if windows else 0
        total = sum(windows.values())
        curve = [100.0]
        at_risk = total
        for age in range(0, max_age + 1):
            d = deaths.get(age, 0)
            if at_risk <= 0:
                break
            curve.append(curve[-1] * (1 - d / at_risk))
            at_risk -= d
        return [round(v, 2) for v in curve]

    def young_firm_failure(self) -> list[tuple[int, int, float]]:
        """Insolvencies of firms aged five or under, by the calendar year the
        insolvency happened, and as a share of the firms that young."""
        events = dict(
            self.rows(
                f"""select extract(year from death_date)::int as y, count(*)
                    from firm_master
                    where exit_class = 'insolvent' and birth_year is not null
                      and death_date is not null
                      and extract(year from death_date)::int - birth_year between 0 and 5
                    group by 1"""
            )
        )
        births = dict(
            self.rows("select birth_year, count(*) from firm_master where birth_year is not null group by 1")
        )
        out = []
        for y in range(self.first, self.last + 1):
            at_risk = sum(births.get(b, 0) for b in range(y - 5, y + 1))
            if at_risk and y in events:
                out.append((y, events[y], 100.0 * events[y] / at_risk))
        return out

    def entry_rate(self) -> list[tuple[int, int, float]]:
        """Incorporations, and incorporations as a share of the active stock.

        The stock is cumulative births minus observed deaths. The death record is
        known to be incomplete, so the stock is too high and the rate too low —
        the page says so, and the extraction that will close the gap is running.
        """
        births = dict(
            self.rows("select birth_year, count(*) from firm_master where birth_year is not null group by 1")
        )
        deaths = dict(
            self.rows(
                "select extract(year from death_date)::int, count(*) from firm_master "
                "where death_date is not null group by 1"
            )
        )
        stock = 0
        out = []
        for y in range(min(births), self.last + 1):
            opening = stock
            stock += births.get(y, 0) - deaths.get(y, 0)
            if y >= self.first and opening > 0:
                out.append((y, births.get(y, 0), 100.0 * births.get(y, 0) / opening))
        return out

    def exit_type_mix(self) -> tuple[list[int], list[tuple[str, list[int]]]]:
        """Terminal notice type by year — the granular view of how firms end."""
        rows = self.rows(
            f"""select extract(year from death_date)::int y, exit_type, count(*)
                from exit_events
                where exit_type is not null and death_date is not null
                  and extract(year from death_date) between {self.first} and {self.last}
                group by 1, 2"""
        )
        years = sorted({int(y) for y, _, _ in rows})
        totals: dict[str, int] = {}
        for _, t, n in rows:
            totals[t] = totals.get(t, 0) + n
        order = sorted(totals, key=lambda t: -totals[t])
        table = {(int(y), t): n for y, t, n in rows}
        return years, [(t, [table.get((y, t), 0) for y in years]) for t in order]


def build_lifecycle(b: Build, F: dict, T: dict, C: dict, ctx: dict) -> None:
    """Survival, hazard, young-firm failure, entry rates and the granular exit
    mix — the additions from the visualisations review."""
    lc = Lifecycle(b.con, ctx["gz_first"], ctx["gz_last"])

    # ── survival curves by birth cohort ─────────────────────────────────────
    bands = lc.cohort_bands()
    colours = ["navy", "red", "blue", "teal"]
    datasets, floor = [], 100.0
    for k, band in enumerate(bands):
        insolvency = lc.survival(band["y0"], band["y1"], True)
        any_exit = lc.survival(band["y0"], band["y1"], False)
        floor = min(floor, min(any_exit))
        colour = colours[k % len(colours)]
        datasets.append(
            dict(line_ds(band["label"] + " \u00b7 insolvency", insolvency, colour,
                         [f"{band['label']}: {pctn(v)} still trading at age {a}"
                          for a, v in enumerate(insolvency)], point=0),
                 tension=0.1)
        )
        datasets.append(
            dict(line_ds(band["label"] + " \u00b7 any exit", any_exit, colour,
                         [f"{band['label']}: {pctn(v)} not yet dissolved at age {a}"
                          for a, v in enumerate(any_exit)], point=0, width=1.5),
                 tension=0.1, borderDash=[4, 3])
        )
    max_age = max(len(d["data"]) for d in datasets) - 1
    lo = 5 * int(floor / 5)
    ya, ymap = value_axis("% still trading", 100, lambda v: pctn(v, 0), vmin=lo, count=4)
    F["surv_bands"] = word(len(bands))
    F["surv_max_age"] = str(max_age)
    oldest = bands[0]
    ins_oldest = lc.survival(oldest["y0"], oldest["y1"], True)
    all_oldest = lc.survival(oldest["y0"], oldest["y1"], False)
    F["surv_oldest_label"] = oldest["label"]
    F["surv_oldest_age"] = str(len(ins_oldest) - 1)
    F["surv_oldest_insolvency"] = pct(100 - ins_oldest[-1], 1)
    F["surv_oldest_anyexit"] = pct(100 - all_oldest[-1], 1)
    F["surv_first_five"] = pct(100 - ins_oldest[min(5, len(ins_oldest) - 1)], 1)
    C["c_survival"] = {
        "type": "line",
        "data": {"labels": [str(a) for a in range(max_age + 1)], "datasets": datasets},
        "options": {**base_options(legend=True, interaction_index=True),
                    "scales": {"x": axis(title="years since incorporation", grid=False,
                                         ticks={"maxTicksLimit": 11}), "y": ya}},
        "tickLabels": {"y": ymap},
    }

    # ── young-firm failure by the year it happened ───────────────────────────
    yf = lc.young_firm_failure()
    labels = [str(y) for y, _, _ in yf]
    counts = [n for _, n, _ in yf]
    rates = [r for _, _, r in yf]
    crisis = max((r for r in yf if 2007 <= r[0] <= 2010), key=lambda r: r[2])
    latest = yf[-1]
    trough = min(yf, key=lambda r: r[2])
    F["young_crisis_year"] = str(crisis[0])
    F["young_crisis_pct"] = pct(crisis[2], 2)
    F["young_crisis_count"] = i(crisis[1])
    F["young_trough_year"] = str(trough[0])
    F["young_trough_pct"] = pct(trough[2], 2)
    F["young_last_year"] = str(latest[0])
    F["young_last_pct"] = pct(latest[2], 2)
    F["young_peak_count_year"] = str(max(yf, key=lambda r: r[1])[0])
    F["young_peak_count"] = i(max(yf, key=lambda r: r[1])[1])
    ya, ymap = value_axis("% of firms aged five or under", max(rates), lambda v: pctn(v, 1))
    y1a, y1map = value_axis("insolvencies", max(counts), compact, position="right", grid=False)
    C["c_young"] = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [
                dict(line_ds("Rate (left)", [round(r, 3) for r in rates], "red",
                             [f"{pctn(r, 2)} of firms aged five or under" for r in rates],
                             fill=True), yAxisID="y"),
                dict(line_ds("Insolvencies (right)", counts, "navy",
                             [f"{i(n)} insolvencies of firms aged five or under" for n in counts],
                             point=0, width=2), yAxisID="y1"),
            ],
        },
        "options": {**base_options(legend=True, interaction_index=True),
                    "scales": {"x": axis(grid=False), "y": ya, "y1": y1a}},
        "tickLabels": {"y": ymap, "y1": y1map},
        "bands": recession_bands(labels),
    }

    # ── entry rate: the ratio view alongside the absolute count ─────────────
    er = [r for r in lc.entry_rate() if r[0] <= ctx["birth_last"]]
    labels = [str(y) for y, _, _ in er]
    F["entry_first_year"] = labels[0]
    F["entry_first_pct"] = pct(er[0][2], 1)
    F["entry_last_year"] = labels[-1]
    F["entry_last_pct"] = pct(er[-1][2], 1)
    F["entry_peak_year"] = str(max(er, key=lambda r: r[2])[0])
    F["entry_peak_pct"] = pct(max(er, key=lambda r: r[2])[2], 1)
    F["entry_change"] = change_phrase(er[0][2], er[-1][2])
    ya, ymap = value_axis("new companies as % of the active stock",
                          max(r for _, _, r in er), lambda v: pctn(v, 0))
    y1a, y1map = value_axis("incorporations", max(n for _, n, _ in er), compact,
                            position="right", grid=False)
    C["c_entry"] = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [
                dict(line_ds("Entry rate (left)", [round(r, 2) for _, _, r in er], "green",
                             [f"{pctn(r, 1)} of the active stock" for _, _, r in er],
                             fill=True), yAxisID="y"),
                dict(line_ds("Incorporations (right)", [n for _, n, _ in er], "mut",
                             [f"{i(n)} new companies" for _, n, _ in er], point=0, width=1.5),
                     yAxisID="y1"),
            ],
        },
        "options": {**base_options(legend=True, interaction_index=True),
                    "scales": {"x": axis(grid=False), "y": ya, "y1": y1a}},
        "tickLabels": {"y": ymap, "y1": y1map},
        "bands": recession_bands(labels),
    }

    # ── index turnover: one line per index, entrants as a share of the index ──
    # Exits mirror entrants almost exactly, because both indices hold a fixed
    # number of constituents, so a single series per index carries the whole
    # story — and the two become directly comparable once divided by size.
    y0, y1 = int(F["panel_start_year"]), int(F["panel_last_year"])
    series = {}
    for key, table, size, colour in (
        ("ftse", "ftse100_membership", INDEX_SIZE["ftse"], "amber"),
        ("sp", "sp500_membership", INDEX_SIZE["sp"], "blue"),
    ):
        rows = b.churn(table, y0, y1)
        series[key] = {
            "rows": [(y, j, 100.0 * j / size) for y, j, _ in rows],
            "mirrored": sum(1 for _, j, l in rows if j == l),
            "n": len(rows),
            "colour": colour,
        }
    labels = [str(y) for y, _, _ in series["ftse"]["rows"]]
    for key, name in (("ftse", "FTSE 100"), ("sp", "S&P 500")):
        rows = series[key]["rows"]
        peak = max(rows, key=lambda r: r[2])
        F[f"churn_{key}_mean"] = pct(sum(r[2] for r in rows) / len(rows), 1)
        F[f"churn_{key}_peak_pct"] = pct(peak[2], 1)
        F[f"churn_{key}_peak_year"] = str(peak[0])
        F[f"churn_{key}_peak_count"] = word(peak[1])
        F[f"churn_{key}_size"] = i(INDEX_SIZE[key])
    ftse_mean = sum(r[2] for r in series["ftse"]["rows"]) / len(series["ftse"]["rows"])
    sp_mean = sum(r[2] for r in series["sp"]["rows"]) / len(series["sp"]["rows"])
    F["churn_ratio"] = times_word(ftse_mean / sp_mean)
    F["churn_first_year"] = labels[0]
    F["churn_last_year"] = labels[-1]
    F["churn_mirrored"] = word(series["ftse"]["mirrored"] + series["sp"]["mirrored"])
    F["churn_observations"] = word(series["ftse"]["n"] + series["sp"]["n"])
    ya, ymap = value_axis("constituents replaced, % of the index",
                          max(r[2] for k in series for r in series[k]["rows"]),
                          lambda v: pctn(v, 0))
    C["c_churn"] = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [
                line_ds(name, [round(r[2], 2) for r in series[key]["rows"]],
                        series[key]["colour"],
                        [f"{name}: {r[1]} of {size} replaced, {pctn(r[2], 1)}"
                         for r in series[key]["rows"]])
                for key, name, size in (("ftse", "FTSE 100", INDEX_SIZE["ftse"]),
                                        ("sp", "S&P 500", INDEX_SIZE["sp"]))
            ],
        },
        "options": {**base_options(legend=True, interaction_index=True),
                    "scales": {"x": axis(grid=False, ticks={"maxTicksLimit": 12}), "y": ya}},
        "tickLabels": {"y": ymap},
        "bands": recession_bands(labels),
    }

    # ── where index turnover happens: departures by value quartile ───────────
    # Aggregate turnover says nothing about which constituents leave. Ranking
    # each year's index by market capitalisation and asking which quartile the
    # departures came from does. Only years in which every constituent carries a
    # market capitalisation can be ranked, so the window is stated on the page.
    qyears = [
        int(y) for y, n in b.rows(
            "select year, count(*) filter(where market_cap_gbp is not null) "
            "from ftse100_compositions group by 1 "
            f"having count(*) filter(where market_cap_gbp is not null) >= {INDEX_SIZE['ftse']} "
            "order by 1"
        )
    ]
    ylist = ",".join(map(str, qyears))
    nextlist = ",".join(str(y + 1) for y in qyears)
    quart = dict(
        (int(q), int(n)) for q, n in b.rows(
            # Identity is company_number, not the ticker: a company that renames its
            # ticker between years would otherwise look like a departure and a new
            # arrival at once, and a reused ticker would hide a real departure.
            # Rows the composition record leaves without a company_number fall back
            # to the ticker so they are counted rather than dropped.
            "with r as (select year, coalesce(company_number, 'CODE:' || code) as id, "
            "  ntile(4) over (partition by year order by market_cap_gbp desc, "
            "                 coalesce(company_number, 'CODE:' || code)) q "
            "  from ftse100_compositions "
            f"  where market_cap_gbp is not null and year in ({ylist})) "
            "select r.q, count(*) from r "
            f"where r.year + 1 in ({nextlist}) "
            "  and not exists (select 1 from ftse100_compositions n "
            "                  where n.year = r.year + 1 "
            "                    and coalesce(n.company_number, 'CODE:' || n.code) = r.id) "
            "group by 1 order by 1"
        )
    )
    qtotal = sum(quart.values())
    qshares = [100.0 * quart.get(k, 0) / qtotal for k in (1, 2, 3, 4)]
    F["quart_events"] = i(qtotal)
    F["quart_years"] = f"{qyears[0]}\u2013{qyears[-1]}"
    F["quart_year_count"] = word(len(qyears))
    F["quart_bottom_pct"] = pct(qshares[3], 1)
    F["quart_top_pct"] = pct(qshares[0], 1)
    F["quart_ratio"] = times_word(qshares[3] / qshares[0])
    ya, ymap = value_axis("% of departures", max(qshares), lambda v: pctn(v, 0))
    C["c_quartile"] = {
        "type": "bar",
        "data": {
            "labels": ["Largest quarter", "Second", "Third", "Smallest quarter"],
            "datasets": [bar_ds([round(v, 1) for v in qshares], PAL["amber"],
                                [f"{pctn(v, 1)} of departures ({quart.get(k, 0)})"
                                 for k, v in zip((1, 2, 3, 4), qshares)])],
        },
        "options": {**base_options(), "scales": {"x": axis(grid=False), "y": ya}},
        "tickLabels": {"y": ymap},
    }

    # ── the granular exit mix over time ─────────────────────────────────────
    years, series = lc.exit_type_mix()
    labels = [str(y) for y in years]
    palette = ["red", "green", "amber", "blue", "teal", "navy"]
    stack = []
    for k, (kind, values) in enumerate(series):
        label = kind.replace("_", " ")
        label = {
            "creditors voluntary winding up": "Creditors' voluntary liquidation",
            "members voluntary winding up": "Members' voluntary (solvent)",
            "winding up order court": "Winding-up order (court)",
            "petition to wind up": "Petition to wind up",
        }.get(label, label[:1].upper() + label[1:])
        colour = palette[k % len(palette)]
        stack.append({
            "label": label,
            "data": values,
            "borderColor": PAL[colour],
            "backgroundColor": PAL[colour],
            "fill": False,
            "pointRadius": 0,
            "borderWidth": 2.5,
            "tension": 0.3,
            "tips": [f"{label}: {i(v)}" for v in values],
        })
    ya, ymap = value_axis("notices", max(max(v) for _, v in series), compact)
    solvent = next((v for k, v in series if "members_voluntary" in k), None)
    F["mixt_solvent_peak_year"] = str(years[solvent.index(max(solvent))])
    F["mixt_solvent_peak"] = i(max(solvent))
    F["mixt_types"] = word(len(series))
    C["c_exit_types"] = {
        "type": "line",
        "data": {"labels": labels, "datasets": stack},
        "options": {**base_options(legend=True, interaction_index=True),
                    "scales": {"x": axis(grid=False, ticks={"maxTicksLimit": 12}),
                               "y": ya}},
        "tickLabels": {"y": ymap},
        "bands": recession_bands(labels),
    }

if __name__ == "__main__":
    sys.exit(main())
