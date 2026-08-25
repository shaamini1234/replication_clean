-- ============================================================================
-- 07_ftse_ch_financials.sql — attach Companies House financials to FTSE 100 firms
-- Run:  psql business_dynamism -f 07_ftse_ch_financials.sql
--
-- FTSE 100 firms are large UK plcs that file FULL accounts, so their revenue,
-- profit and assets are already in financial_filings — joinable by company
-- number. This builds ftse100_financials: each constituent-year with its market
-- cap PLUS its CH financials. CH accounts start 2008, so pre-2008 FTSE years
-- won't have CH financials (structural). Safe to re-run.
-- ============================================================================

DROP TABLE IF EXISTS ftse100_financials;
CREATE TABLE ftse100_financials AS
WITH ftse AS (
    SELECT
        year,
        name,
        market_cap_gbp,
        CASE WHEN company_number ~ '^[0-9]{1,8}$' THEN lpad(company_number,8,'0')
             ELSE upper(trim(company_number)) END AS cn
    FROM ftse100_compositions
    WHERE company_number IS NOT NULL
)
SELECT
    f.year,
    f.cn AS company_number,
    f.name,
    f.market_cap_gbp,
    p.total_assets,
    p.net_assets,
    p.turnover,
    p.operating_profit,
    p.employees,
    p.size_class
FROM ftse f
LEFT JOIN firm_year_panel p
       ON p.company_number = f.cn AND p.fiscal_year = f.year;

CREATE INDEX ON ftse100_financials (company_number, year);

-- ============================================================================
-- QA
-- ============================================================================
\echo '--- FTSE constituent-years matched to CH financials, 2008+ ---'
SELECT
    count(*)                                        AS ftse_firm_years,
    count(*) FILTER (WHERE year >= 2008)            AS since_2008,
    count(total_assets) FILTER (WHERE year >= 2008) AS with_ch_assets,
    round(100.0*count(total_assets) FILTER (WHERE year>=2008)
          / nullif(count(*) FILTER (WHERE year>=2008),0),0) AS pct_matched
FROM ftse100_financials;

\echo '--- revenue coverage for FTSE firms (should beat the ~2% whole-population rate) ---'
SELECT
    round(100.0*count(turnover) FILTER (WHERE year>=2008)
          / nullif(count(*) FILTER (WHERE year>=2008),0),0) AS pct_with_revenue,
    round(100.0*count(operating_profit) FILTER (WHERE year>=2008)
          / nullif(count(*) FILTER (WHERE year>=2008),0),0) AS pct_with_op_profit
FROM ftse100_financials;

\echo '--- sample: recent FTSE firms with market cap + CH financials ---'
SELECT name, year, round(market_cap_gbp/1e9,1) AS mktcap_bn,
       round(total_assets/1e9,1) AS assets_bn, round(turnover/1e9,1) AS revenue_bn, employees
FROM ftse100_financials
WHERE year=2022 AND total_assets IS NOT NULL
ORDER BY market_cap_gbp DESC NULLS LAST LIMIT 8;
