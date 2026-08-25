-- ============================================================================
-- 05_combined_firm_year.sql  —  THE cohesive dataset (complete)
-- Run:  psql companies_house_v2 -f 05_combined_firm_year.sql
--
-- One long table holding EVERYTHING:
--   Part 1 (row_source='ch_filing')       : every CH firm-year, with the
--                                            Gazette insolvency outcome attached.
--   Part 2 (row_source='gazette_exit_only'): every insolvency/exit that has NO
--                                            CH accounts — i.e. pre-2008 deaths
--                                            (CH financials start 2008) and
--                                            never-filers. Financials are NULL;
--                                            the exit event is preserved.
--
-- This guarantees no insolvency is dropped just because it predates CH
-- financial coverage. Columns per row:
--   ...all firm_year_panel financial columns... (NULL for gazette_exit_only)
--   ever_exit, exit_class, exit_type, insolvency_date, had_prior_petition,
--   years_to_exit, is_final_pre_exit_filing, row_source
--
-- Depends on: firm_year_panel (step 2), exit_events (step 1). Safe to re-run.
-- ============================================================================

DROP TABLE IF EXISTS combined_firm_year;

-- ---- Part 1: CH firm-years + Gazette outcome -------------------------------
CREATE TABLE combined_firm_year AS
WITH last_pre AS (
    SELECT DISTINCT ON (p.company_number)
        p.company_number, p.fiscal_year AS last_pre_year
    FROM firm_year_panel p
    JOIN exit_events e ON e.company_number_norm = p.company_number
    WHERE p.period_end < e.death_date
    ORDER BY p.company_number, p.period_end DESC
)
SELECT
    p.*,
    (e.company_number_norm IS NOT NULL)                 AS ever_exit,
    e.exit_class,
    e.exit_type,
    e.death_date                                        AS insolvency_date,
    e.had_prior_petition,
    CASE WHEN e.death_date IS NOT NULL
         THEN extract(year from e.death_date)::int - p.fiscal_year END AS years_to_exit,
    (lp.company_number IS NOT NULL AND lp.last_pre_year = p.fiscal_year) AS is_final_pre_exit_filing,
    'ch_filing'::text                                   AS row_source
FROM firm_year_panel p
LEFT JOIN exit_events e  ON e.company_number_norm = p.company_number
LEFT JOIN last_pre    lp ON lp.company_number     = p.company_number;

-- ---- Part 2: insolvencies with NO CH accounts (pre-2008 + never-filers) -----
-- One row per such company; financial columns left NULL by omission.
INSERT INTO combined_firm_year
    (company_number, fiscal_year,
     ever_exit, exit_class, exit_type, insolvency_date, had_prior_petition,
     years_to_exit, is_final_pre_exit_filing, row_source)
SELECT
    e.company_number_norm,
    extract(year from e.death_date)::int,
    true, e.exit_class, e.exit_type, e.death_date, e.had_prior_petition,
    0, false, 'gazette_exit_only'
FROM exit_events e
WHERE NOT EXISTS (
    SELECT 1 FROM firm_year_panel p WHERE p.company_number = e.company_number_norm
);

CREATE INDEX ON combined_firm_year (company_number);
CREATE INDEX ON combined_firm_year (fiscal_year);
CREATE INDEX ON combined_firm_year (exit_class);
CREATE INDEX ON combined_firm_year (ever_exit);
CREATE INDEX ON combined_firm_year (row_source);

-- ============================================================================
-- QA OUTPUT
-- ============================================================================
\echo '--- rows by source (gazette_exit_only = insolvencies w/o CH accounts) ---'
SELECT row_source, count(*) AS rows,
       count(DISTINCT company_number) AS companies,
       min(fiscal_year) AS min_year, max(fiscal_year) AS max_year
FROM combined_firm_year GROUP BY 1 ORDER BY 1;

\echo '--- ALL insolvencies by year, incl. pre-2008 (proof nothing is dropped) ---'
SELECT fiscal_year AS insolvency_year, count(*) AS insolvent_firms
FROM combined_firm_year
WHERE exit_class = 'insolvent' AND is_final_pre_exit_filing = false
      AND row_source = 'gazette_exit_only'
      AND fiscal_year < 2008
GROUP BY 1 ORDER BY 1;

\echo '--- balance sheet running down to insolvency (median net worth by years-out) ---'
SELECT years_to_exit,
       count(*) AS firm_years,
       round(percentile_cont(0.5) within group (order by net_assets)
             FILTER (WHERE net_assets IS NOT NULL)::numeric) AS median_net_worth
FROM combined_firm_year
WHERE exit_class = 'insolvent' AND years_to_exit BETWEEN 0 AND 5
GROUP BY 1 ORDER BY 1;
