#!/usr/bin/env python3
"""build_handover_charts.py — the coverage charts embedded in HANDOVER.md.

Every figure is read from the canonical DuckDB, so the charts and the prose in
the handover cannot drift apart. Re-run after any refresh:

    ./venv/bin/python python/build_handover_charts.py

Writes PNGs to docs/handover/.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "handover"
DB_CANDIDATES = [
    REPO / "database" / "business_dynamism_v2_20260824d.duckdb",
    REPO.parent / "business_dynamism-master" / "business_dynamism_shaamini"
    / "database" / "business_dynamism_v2_20260824d.duckdb",
]

INK, MUT, GRID = "#1a1c22", "#5c6270", "#e2e0da"
NAVY, BLUE, TEAL, AMBER, RED, GREEN = "#1f3864", "#2e6fb0", "#2a8f86", "#c8860a", "#b5432f", "#4a7a45"

plt.rcParams.update({
    "figure.dpi": 160, "savefig.dpi": 160, "font.size": 9,
    "text.color": INK, "axes.labelcolor": MUT, "xtick.color": MUT, "ytick.color": MUT,
    "axes.edgecolor": GRID, "axes.linewidth": 0.8, "grid.color": GRID, "grid.linewidth": 0.6,
    "figure.facecolor": "white", "axes.facecolor": "white", "legend.frameon": False,
})


def db() -> Path:
    for p in DB_CANDIDATES:
        if p.exists():
            return p
    sys.exit("No DuckDB found; run from the repo with database/ populated.")


def style(ax, ylabel=None, pct=False):
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if ylabel:
        ax.set_ylabel(ylabel)
    if pct:
        ax.set_ylim(0, 100)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ docs/handover/{name}")


def main() -> int:
    con = duckdb.connect(str(db()), read_only=True)
    q = lambda s: con.execute(s).fetchall()
    print("handover charts")

    # ── 1. S&P 500 parameter coverage by fiscal year ─────────────────────────
    series = [("Net income", "net_income", GREEN), ("Total assets", "total_assets", NAVY),
              ("Revenue", "revenue", BLUE), ("Shares outstanding", "shares_outstanding", TEAL),
              ("Market cap", "market_cap", AMBER), ("Employees", "employees", RED)]
    rows = q("""select fiscal_year, count(*),
                       count(net_income), count(total_assets), count(revenue),
                       count(shares_outstanding), count(market_cap), count(employees)
                from sp500_consolidated where fiscal_year <= 2024 group by 1 order by 1""")
    years = [r[0] for r in rows]
    fig, ax = plt.subplots(figsize=(7.6, 3.4))
    for k, (label, _, colour) in enumerate(series):
        ax.plot(years, [100 * r[2 + k] / r[1] for r in rows], color=colour, lw=1.9, label=label)
    ax.axvline(2009, color=MUT, lw=0.8, ls=":")
    ax.annotate("SEC XBRL mandate", (2009, 96), xytext=(4, 0), textcoords="offset points",
                fontsize=7.5, color=MUT, va="top")
    style(ax, "coverage of symbol-years", pct=True)
    ax.set_title("S&P 500: parameter coverage by fiscal year", loc="left", fontsize=10.5, color=INK)
    ax.legend(ncol=3, fontsize=8, loc="lower right", bbox_to_anchor=(1.0, -0.02))
    save(fig, "sp500_coverage.png")

    # ── 2. FTSE 100 parameter coverage by year ───────────────────────────────
    rows = q("""select year, count(*),
                       count(annual_dividend_pence), count(year_end_price_pence),
                       count(shares_outstanding), count(market_cap_gbp), count(total_assets)
                from ftse100_consolidated where year between 1983 and 2024 group by 1 order by 1""")
    years = [r[0] for r in rows]
    fig, ax = plt.subplots(figsize=(7.6, 3.4))
    for k, (label, colour) in enumerate([("Dividend / share", TEAL), ("Share price", BLUE),
                                         ("Shares outstanding", NAVY), ("Market cap", AMBER),
                                         ("Revenue / profit / assets", RED)]):
        ax.plot(years, [100 * r[2 + k] / r[1] for r in rows], color=colour, lw=1.9, label=label)
    style(ax, "coverage of constituent-years", pct=True)
    ax.set_title("FTSE 100: parameter coverage by year", loc="left", fontsize=10.5, color=INK)
    ax.legend(ncol=2, fontsize=8, loc="upper left")
    save(fig, "ftse100_coverage.png")

    # ── 3. Formations and exits per year ─────────────────────────────────────
    births = dict(q("select birth_year, count(*) from firm_master "
                    "where birth_year between 1999 and 2024 group by 1"))
    exits = dict(q("select extract(year from death_date)::int, count(*) from exit_events "
                   "where extract(year from death_date) between 1999 and 2024 "
                   "and exit_class = 'insolvent' group by 1"))
    yrs = sorted(births)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.8, 3.0))
    a1.fill_between(yrs, [births[y] for y in yrs], color=GREEN, alpha=0.16)
    a1.plot(yrs, [births[y] for y in yrs], color=GREEN, lw=2)
    style(a1, "incorporations")
    a1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v/1000:.0f}k"))
    a1.set_title("New companies per year", loc="left", fontsize=10, color=INK)
    a2.fill_between(yrs, [exits.get(y, 0) for y in yrs], color=RED, alpha=0.14)
    a2.plot(yrs, [exits.get(y, 0) for y in yrs], color=RED, lw=2)
    style(a2, "insolvencies")
    a2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v/1000:.0f}k"))
    a2.set_title("Insolvencies per year", loc="left", fontsize=10, color=INK)
    save(fig, "population_pulse.png")

    return 0


if __name__ == "__main__":
    sys.exit(main())
