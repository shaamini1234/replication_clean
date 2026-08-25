-- ============================================================================
-- 02_firm_year_panel.sql  —  Step 2 of the combined build
-- Run locally:  psql companies_house_v2 -f 02_firm_year_panel.sql
--
-- Builds firm_year_panel: one cleaned, deduped row per company per fiscal year
-- from financial_filings (v2, 48-col). Foundation for panel analysis and for
-- the pre-death financial snapshot in step 3.
--
-- Dedupe rule (documented): one row per (company_number, fiscal_year), keeping
-- the highest-quality filing — full accounts first, then most core fields
-- populated, then latest period_end, then largest total_assets. NOTE: group
-- consolidated vs subsidiary accounts are DIFFERENT company numbers, so they
-- are NOT collapsed here; cross-group double-counting remains a documented
-- limitation for economy-wide sums (not a within-company dedupe issue).
--
-- fiscal_year = calendar year of period_end. period_end filtered to 2007-2027
-- to drop filer-typo dates. Safe to re-run.
-- ============================================================================

DROP TABLE IF EXISTS firm_year_panel;
CREATE TABLE firm_year_panel AS
SELECT DISTINCT ON (company_number, extract(year from period_end)::int)
    company_number,
    extract(year from period_end)::int      AS fiscal_year,
    period_start,
    period_end,
    -- classification / meta
    size_class,
    size_basis,
    accounts_type,
    accounting_standard,
    audit_status,
    legal_form,
    dormant,
    -- headline balance sheet (well populated)
    total_assets,
    net_assets,
    current_assets,
    working_capital,
    cash,
    employees,
    -- P&L (sparse — see limitations; carried for the ~2% that disclose)
    turnover,
    gross_profit,
    operating_profit,
    profit_loss,
    staff_costs,
    -- balance-sheet detail (rich post-2015 FRS-102 era)
    retained_earnings,
    share_capital,
    creditors_short,
    creditors_long,
    debtors,
    inventories,
    trade_creditors,
    provisions,
    ppe_gross_cost,
    tangible_fixed_assets,
    intangible_assets,
    -- derived
    (net_assets IS NOT NULL AND net_assets < 0) AS net_assets_negative
FROM financial_filings
WHERE period_end BETWEEN '2007-01-01' AND '2027-12-31'
ORDER BY
    company_number,
    extract(year from period_end)::int,
    (accounts_type = 'full') DESC NULLS LAST,          -- prefer full disclosure
    ( (total_assets IS NOT NULL)::int
    + (net_assets   IS NOT NULL)::int
    + (employees    IS NOT NULL)::int
    + (turnover     IS NOT NULL)::int ) DESC,          -- then most core fields
    period_end DESC,                                    -- then latest period
    total_assets DESC NULLS LAST,                       -- then largest
    id DESC;

CREATE INDEX ON firm_year_panel (company_number);
CREATE INDEX ON firm_year_panel (company_number, fiscal_year);
CREATE INDEX ON firm_year_panel (fiscal_year);

-- ============================================================================
-- QA OUTPUT
-- ============================================================================
\echo '--- dedupe: source rows (2007-2027) vs panel rows kept ---'
SELECT
    (SELECT count(*) FROM financial_filings
       WHERE period_end BETWEEN '2007-01-01' AND '2027-12-31') AS source_rows,
    (SELECT count(*) FROM firm_year_panel)                     AS panel_rows,
    (SELECT count(*) FROM financial_filings
       WHERE period_end BETWEEN '2007-01-01' AND '2027-12-31')
      - (SELECT count(*) FROM firm_year_panel)                 AS collapsed;

\echo '--- integrity: zero (company, year) duplicates expected ---'
SELECT count(*) AS dup_company_year FROM (
    SELECT company_number, fiscal_year FROM firm_year_panel
    GROUP BY 1,2 HAVING count(*) > 1) d;

\echo '--- core-field coverage by year (the fields analysis will use) ---'
SELECT fiscal_year,
    count(*) AS firm_years,
    round(100.0*count(total_assets)/count(*),0) AS pct_total_assets,
    round(100.0*count(net_assets)/count(*),0)   AS pct_net_assets,
    round(100.0*count(employees)/count(*),0)    AS pct_employees,
    round(100.0*count(turnover)/count(*),0)     AS pct_turnover,
    round(100.0*count(trade_creditors)/count(*),0) AS pct_trade_cred
FROM firm_year_panel
WHERE fiscal_year BETWEEN 2008 AND 2026
GROUP BY 1 ORDER BY 1;

\echo '--- size_class distribution ---'
SELECT coalesce(size_class,'(null)') AS size_class, count(*) AS firm_years
FROM firm_year_panel GROUP BY 1 ORDER BY 2 DESC;
