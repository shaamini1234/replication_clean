# database — the canonical combined database
business_dynamism_v2_<date>.duckdb : single-file DuckDB, every table, readable with no cloud.
.duckdb.zst : compressed backup. Rebuild the .zst locally with:  zstd business_dynamism_v2_<date>.duckdb
This is the source of truth. Neon is only cloud staging; local Postgres holds the raw financial_filings.
