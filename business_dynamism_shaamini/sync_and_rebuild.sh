#!/usr/bin/env bash
# ============================================================================
# sync_and_rebuild.sh — make the LOCAL Postgres the single source of truth.
#
# Run this on your Mac (it needs BOTH the internet, to read Neon, and your
# local Postgres). My sandbox cannot reach local Postgres, so this is a
# you-run-it script. Safe to re-run; it replaces the synced tables each time.
#
#   1. Pull the cloud-only (Neon) tables down into local `business_dynamism`
#   2. Rebuild the derived spine/panels from the SQL scripts (in order)
#   3. Re-export the whole database to a fresh dated Parquet snapshot
#
# After it finishes, local Postgres holds everything and Neon is just where
# the crawlers stage new data until the next sync.
#
# Usage:
#   chmod +x sync_and_rebuild.sh
#   ./sync_and_rebuild.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

# ---------------- CONFIG (edit here as the project grows) -------------------
# Neon credential comes from .env at the repo root (gitignored), not from this file.
[ -f "$(dirname "$0")/.env" ] && { set -a; . "$(dirname "$0")/.env"; set +a; }
NEON="${NEON_URL:?set NEON_URL in .env — see .env.example}"
LOCAL_DB="business_dynamism"

# Neon tables to bring down to local. Add new crawl/API tables here as you make
# them (e.g. ch_ixbrl_accounts once it's populated).
SYNC_TABLES=(
  gazette_events
  ch_company_profile
  ftse100_membership
  ftse100_fundamentals
  ftse100_compositions
  ftse100_changes
  ftse100_mapping
  sp500_financials
  sp500_membership
  sp500_companies
  sp500_companies_full
)
# Big staging tables — usually not needed for analysis. Uncomment to include.
# SYNC_TABLES+=( companies strikeoff_candidates ch_lookup_queue )

STAMP="$(date +%Y%m%d)"
PARQUET_DIR="output/v1_${STAMP}"
# ----------------------------------------------------------------------------

echo "==============================================================="
echo " STEP 1/3  —  Neon  ->  local Postgres ($LOCAL_DB)"
echo "==============================================================="
for t in "${SYNC_TABLES[@]}"; do
  echo "  syncing $t ..."
  # dump one table from Neon (schema + data, replacing any local copy) and load it
  pg_dump "$NEON" --table="public.$t" --clean --if-exists --no-owner --no-privileges \
    | psql "$LOCAL_DB" -q -v ON_ERROR_STOP=1
  # quick row count so you can see it landed
  psql "$LOCAL_DB" -tAc "SELECT '    -> ' || count(*) || ' rows in $t' FROM $t;"
done

echo
echo "==============================================================="
echo " STEP 2/3  —  rebuild derived tables from sql/ (in order)"
echo "==============================================================="
for f in sql/0*.sql sql/1*.sql; do
  echo "  running $f ..."
  psql "$LOCAL_DB" -q -v ON_ERROR_STOP=1 -f "$f"
done

echo
echo "==============================================================="
echo " STEP 3/3  —  export full database to Parquet snapshot"
echo "==============================================================="
mkdir -p "$PARQUET_DIR"
# 04_export_parquet.py writes every table to Parquet; point it at this dated dir
PARQUET_OUT="$PARQUET_DIR" python3 python/04_export_parquet.py

echo
echo "==============================================================="
echo " DONE.  Local Postgres '$LOCAL_DB' is now the single source of truth."
echo " Parquet snapshot: $PARQUET_DIR"
echo "==============================================================="
