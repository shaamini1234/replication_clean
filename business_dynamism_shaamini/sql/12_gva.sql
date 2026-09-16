-- ============================================================================
-- 12_gva.sql — firm-level Gross Value Added (income method)
-- Run:  psql business_dynamism -f 12_gva.sql
--
-- GVA ≈ staff_costs + operating_profit + depreciation
--   (labour compensation + gross operating surplus)
--
-- HONEST LIMIT: needs the P&L, which micro/small firms legally omit — so this is
-- only computable for the ~1% filing full accounts (large/medium firms). It is
-- NOT an economy-wide figure. For total/sector GVA use ONS ABS aGVA as an
-- overlay. Uses raw financial_filings (which has depreciation; the panel doesn't).
-- ============================================================================

DROP TABLE IF EXISTS firm_gva;
CREATE TABLE firm_gva AS
SELECT DISTINCT ON (company_number, extract(year from period_end)::int)
    company_number,
    extract(year from period_end)::int AS fiscal_year,
    size_class,
    staff_costs, operating_profit, depreciation, employees,
    (staff_costs + operating_profit + depreciation) AS gva
FROM financial_filings
WHERE period_end BETWEEN '2008-01-01' AND '2027-12-31'
  AND staff_costs IS NOT NULL AND operating_profit IS NOT NULL AND depreciation IS NOT NULL
  -- Exclude filings flagged as false by flag_implausible_filings.py. Three
  -- companies filed returns in which every monetary figure is absurd (one
  -- reports staff costs of GBP 239.6bn and an operating loss of GBP 354.4bn);
  -- all three are GVA-computable and would otherwise dominate the aggregates.
  AND COALESCE(filing_suspect, false) = false
ORDER BY company_number, extract(year from period_end)::int, period_end DESC;

CREATE INDEX ON firm_gva (company_number, fiscal_year);

-- ============================================================================
-- QA / results
-- ============================================================================
\echo '--- how many firm-years have a computable GVA (the coverage reality) ---'
SELECT
  (SELECT count(*) FROM financial_filings WHERE period_end BETWEEN '2008-01-01' AND '2027-12-31') AS all_filings,
  (SELECT count(*) FROM firm_gva) AS gva_computable,
  round(100.0*(SELECT count(*) FROM firm_gva)
        /(SELECT count(*) FROM financial_filings WHERE period_end BETWEEN '2008-01-01' AND '2027-12-31'),2) AS pct;

\echo '--- computable GVA firm-years by size band (mostly large/medium) ---'
SELECT coalesce(size_class,'(unknown)') AS size_class, count(*) AS firm_years,
       round(percentile_cont(0.5) within group (order by gva)::numeric/1e6,2) AS median_gva_m
FROM firm_gva WHERE gva IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;

\echo '--- productivity: median GVA per employee, by size (where employees present) ---'
SELECT coalesce(size_class,'(unknown)') AS size_class,
       count(*) FILTER (WHERE employees>0) AS n,
       round(percentile_cont(0.5) within group (order by gva/nullif(employees,0))
             FILTER (WHERE employees>0)::numeric) AS median_gva_per_employee
FROM firm_gva WHERE gva IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;

\echo '--- total computable GVA by year ($ = £; sum of the covered subset only, NOT economy-wide) ---'
SELECT fiscal_year, count(*) firms, round(sum(gva)/1e9,1) AS gva_bn_covered_subset
FROM firm_gva WHERE fiscal_year BETWEEN 2010 AND 2024 GROUP BY 1 ORDER BY 1;
