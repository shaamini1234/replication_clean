"""
combined.py — analysis layer for the combined Gazette x Companies House dataset.

Reads the Parquet files produced by 04_export_parquet.py. Nothing here touches
Postgres, so analysis is portable and reproducible from the Parquet alone.

Two ways to use it:
  1. Small tables straight to pandas:
        from combined import load
        deaths = load("firm_master")          # 7.9M rows — fine in memory
        exits  = load("exit_events")
  2. SQL over the Parquet via DuckDB (best for the 39M-row panel — never loads
     it all into memory):
        from combined import q
        q("SELECT fiscal_year, count(*) FROM firm_year_panel GROUP BY 1 ORDER BY 1")

Requires: pip install duckdb pandas
"""
import os
import duckdb

_OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "output"))
TABLES = {
    "exit_events":     os.path.join(_OUT, "exit_events.parquet"),
    "firm_master":     os.path.join(_OUT, "firm_master.parquet"),
    "firm_year_panel": os.path.join(_OUT, "firm_year_panel.parquet"),
}


def _con():
    """A DuckDB connection with the three tables registered as views."""
    con = duckdb.connect()
    for name, path in TABLES.items():
        if os.path.exists(path):
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{path}')")
    return con


def q(sql: str):
    """Run SQL over the Parquet tables; returns a pandas DataFrame.
    Table names exit_events / firm_master / firm_year_panel are available."""
    return _con().execute(sql).df()


def load(name: str):
    """Load a whole table into a pandas DataFrame (use for the small ones)."""
    if name not in TABLES:
        raise KeyError(f"unknown table {name!r}; choose from {list(TABLES)}")
    return duckdb.sql(f"SELECT * FROM read_parquet('{TABLES[name]}')").df()


# ---- ready-made analyses (examples; extend freely) -------------------------

def insolvent_deaths_by_year():
    return q("""
        SELECT extract(year from death_date)::int AS year,
               count(*) AS insolvent_deaths
        FROM firm_master
        WHERE exit_class = 'insolvent' AND death_date >= DATE '2008-01-01'
        GROUP BY 1 ORDER BY 1
    """)


def balance_sheet_insolvency_before_death():
    """Share of deaths that were already balance-sheet insolvent at last accounts."""
    return q("""
        SELECT exit_class,
               count(*) FILTER (WHERE has_pre_death_accounts) AS with_accounts,
               round(100.0*count(*) FILTER (WHERE has_pre_death_accounts AND net_assets_negative)
                     / nullif(count(*) FILTER (WHERE has_pre_death_accounts),0),1) AS pct_neg_net_assets
        FROM firm_master WHERE exit_observed GROUP BY 1 ORDER BY 2 DESC NULLS LAST
    """)


def match_status_summary():
    return q("""
        SELECT match_status, count(*) AS companies,
               round(100.0*count(*)/sum(count(*)) over (),1) AS pct
        FROM firm_master GROUP BY 1 ORDER BY 2 DESC
    """)


def deaths_by_size_class(year_from=2008):
    """Insolvent deaths cross-tabbed by pre-death size band."""
    return q(f"""
        SELECT coalesce(size_class,'(unknown)') AS size_class,
               count(*) AS insolvent_deaths
        FROM firm_master
        WHERE exit_class='insolvent' AND death_date >= DATE '{year_from}-01-01'
        GROUP BY 1 ORDER BY 2 DESC
    """)


if __name__ == "__main__":
    print("match_status:\n", match_status_summary(), "\n")
    print("insolvent deaths per year:\n", insolvent_deaths_by_year(), "\n")
    print("balance-sheet insolvency before death:\n", balance_sheet_insolvency_before_death())
