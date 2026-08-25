-- ============================================================================
-- 03_firm_master.sql  —  Step 3 of the combined build
-- Run locally:  psql companies_house_v2 -f 03_firm_master.sql
-- Depends on: exit_events (step 1), firm_year_panel (step 2), gazette_classified.
--
-- Builds firm_master: ONE row per company across the whole population, the
-- publish-ready analysis spine. Universe = every company that ever filed
-- accounts OR ever had a Gazette exit. Each row carries:
--   - life span proxy (first/last filing year, n filings)
--   - death (if observed): date, type, insolvent/solvent class
--   - a financial snapshot: pre-death accounts for dead firms, latest accounts
--     for firms with no observed exit
--   - match_status: how the company joins across the two sources (nothing
--     dropped — every source company lands here with a status)
--
-- match_status values:
--   matched        : has an exit AND >=1 CH filing
--   no_accounts    : has an exit but never filed accounts (micro/shell)
--   invalid_key    : has an exit but an unusable company number (excluded join)
--   alive_no_exit  : has filings, no Gazette exit observed (NOT proof of survival
--                    -- could be a strike-off, which is not gazetted)
-- Safe to re-run.
-- ============================================================================

-- helpful index for the snapshot lookups (idempotent)
CREATE INDEX IF NOT EXISTS idx_fyp_cn_pe ON firm_year_panel (company_number, period_end);

DROP TABLE IF EXISTS firm_master;
CREATE TABLE firm_master AS
WITH
exits AS (
    SELECT company_number_norm AS cn, death_date, exit_type, exit_class,
           had_prior_petition
    FROM exit_events
),
invalid_exits AS (                       -- terminal events with unusable keys
    SELECT company_number_norm AS cn, min(event_date) AS death_date
    FROM gazette_classified
    WHERE key_status = 'invalid' AND event_class IN ('insolvent','solvent')
    GROUP BY 1
),
panel_agg AS (
    SELECT company_number AS cn,
           min(fiscal_year) AS first_filing_year,
           max(fiscal_year) AS last_filing_year,
           count(*)         AS n_filing_years
    FROM firm_year_panel GROUP BY 1
),
snap_dead AS (                           -- last accounts strictly before death
    SELECT DISTINCT ON (p.company_number)
        p.company_number AS cn, p.period_end AS snap_period_end, p.fiscal_year AS snap_year,
        p.total_assets, p.net_assets, p.employees, p.size_class, p.turnover,
        p.net_assets_negative, 'pre_death'::text AS snapshot_basis
    FROM firm_year_panel p JOIN exits e ON e.cn = p.company_number
    WHERE p.period_end < e.death_date
    ORDER BY p.company_number, p.period_end DESC
),
snap_alive AS (                          -- latest accounts for firms w/ no exit
    SELECT DISTINCT ON (p.company_number)
        p.company_number AS cn, p.period_end AS snap_period_end, p.fiscal_year AS snap_year,
        p.total_assets, p.net_assets, p.employees, p.size_class, p.turnover,
        p.net_assets_negative, 'latest_alive'::text AS snapshot_basis
    FROM firm_year_panel p
    LEFT JOIN exits e ON e.cn = p.company_number
    WHERE e.cn IS NULL
    ORDER BY p.company_number, p.period_end DESC
),
snapshot AS (SELECT * FROM snap_dead UNION ALL SELECT * FROM snap_alive),
universe AS (
    SELECT cn FROM panel_agg
    UNION SELECT cn FROM exits
    UNION SELECT cn FROM invalid_exits
)
SELECT
    u.cn                                             AS company_number,
    -- life span (proxy; birth for never-filers is unknown)
    pa.first_filing_year,
    pa.last_filing_year,
    coalesce(pa.n_filing_years, 0)                   AS n_filing_years,
    CASE WHEN pa.first_filing_year IS NOT NULL THEN 'first_filing'
         ELSE 'unknown' END                          AS birth_source,
    -- death
    (e.death_date IS NOT NULL OR ie.death_date IS NOT NULL) AS exit_observed,
    coalesce(e.death_date, ie.death_date)            AS death_date,
    e.exit_type,
    e.exit_class,
    e.had_prior_petition,
    -- financial snapshot (pre-death for dead, latest for alive)
    s.snapshot_basis,
    s.snap_period_end                                AS snapshot_period_end,
    s.snap_year                                      AS snapshot_fiscal_year,
    s.size_class,
    s.total_assets,
    s.net_assets,
    s.employees,
    s.turnover,
    s.net_assets_negative,
    (s.snapshot_basis = 'pre_death')                 AS has_pre_death_accounts,
    CASE WHEN e.death_date IS NOT NULL AND s.snap_period_end IS NOT NULL
         THEN (e.death_date - s.snap_period_end) END AS days_death_after_last_accounts,
    -- how the company joins across sources
    CASE
        WHEN ie.cn IS NOT NULL                       THEN 'invalid_key'
        WHEN e.death_date IS NOT NULL AND pa.cn IS NOT NULL THEN 'matched'
        WHEN e.death_date IS NOT NULL AND pa.cn IS NULL     THEN 'no_accounts'
        ELSE 'alive_no_exit'
    END                                              AS match_status
FROM universe u
LEFT JOIN panel_agg     pa ON pa.cn = u.cn
LEFT JOIN exits         e  ON e.cn  = u.cn
LEFT JOIN invalid_exits ie ON ie.cn = u.cn
LEFT JOIN snapshot      s  ON s.cn  = u.cn;

CREATE INDEX ON firm_master (company_number);
CREATE INDEX ON firm_master (match_status);
CREATE INDEX ON firm_master (death_date);

-- ============================================================================
-- QA OUTPUT
-- ============================================================================
\echo '--- match_status distribution (the whole universe, nothing dropped) ---'
SELECT match_status, count(*) AS companies,
       round(100.0*count(*)/sum(count(*)) over (),1) AS pct
FROM firm_master GROUP BY 1 ORDER BY 2 DESC;

\echo '--- among observed deaths: pre-death accounts available? ---'
SELECT exit_class,
       count(*) AS deaths,
       count(*) FILTER (WHERE has_pre_death_accounts) AS with_pre_death_accounts,
       round(100.0*count(*) FILTER (WHERE has_pre_death_accounts)/count(*),1) AS pct
FROM firm_master WHERE exit_observed GROUP BY 1 ORDER BY 2 DESC;

\echo '--- balance-sheet insolvency BEFORE death (negative net assets at last accounts) ---'
SELECT exit_class,
       count(*) FILTER (WHERE has_pre_death_accounts) AS with_accounts,
       count(*) FILTER (WHERE has_pre_death_accounts AND net_assets_negative) AS neg_net_assets,
       round(100.0*count(*) FILTER (WHERE has_pre_death_accounts AND net_assets_negative)
             / nullif(count(*) FILTER (WHERE has_pre_death_accounts),0),1) AS pct_insolvent_balance_sheet
FROM firm_master WHERE exit_observed GROUP BY 1 ORDER BY 2 DESC;

\echo '--- filing-silence gap before death (months) ---'
SELECT
    round((avg(days_death_after_last_accounts))::numeric/30.0,1)          AS mean_months,
    round((percentile_cont(0.5) within group
           (order by days_death_after_last_accounts))::numeric/30.0,1)    AS median_months
FROM firm_master WHERE has_pre_death_accounts;

\echo '--- insolvent deaths per year (2008+), a dynamism teaser ---'
SELECT extract(year from death_date)::int AS year, count(*) AS insolvent_deaths
FROM firm_master
WHERE exit_class = 'insolvent' AND death_date >= '2008-01-01'
GROUP BY 1 ORDER BY 1;
