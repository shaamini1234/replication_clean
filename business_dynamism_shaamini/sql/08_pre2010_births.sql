-- ============================================================================
-- 08_pre2010_births.sql — estimate birth YEAR for dead firms the register/API
-- can't give (mostly pre-2010, aged off Companies House).
-- Run:  psql business_dynamism -f 08_pre2010_births.sql
--
-- Method: UK company numbers are issued sequentially, so a number pins the
-- incorporation window tightly. We calibrate number -> incorporation year on
-- the 5.7M live companies (which have both), then estimate for dead firms.
-- Validated: 5,000-number buckets span ~days of incorporations, so year-level
-- estimates are reliable.
--
-- PROVENANCE (per requirement):
--   birth_precision = 'day'            + birth_url = CH company page  (registry)
--   birth_precision = 'year_estimated' + birth_url = NULL             (estimate)
-- Estimates are never given a fake source URL — they are derived, not looked up.
-- Precedence (best first): registry date > CH-API date (pulled later) > estimate.
-- Safe to re-run.
-- ============================================================================

-- 1. calibration: median incorporation year per 5,000-number bucket (E&W numeric)
DROP TABLE IF EXISTS birth_calibration;
CREATE TABLE birth_calibration AS
SELECT ("CompanyNumber"::bigint / 5000) AS bucket,
       round(percentile_cont(0.5) within group (
           order by extract(year from to_date("IncorporationDate",'DD/MM/YYYY'))))::int AS est_year
FROM companies
WHERE "CompanyNumber" ~ '^[0-9]{8}$'
  AND "IncorporationDate" ~ '^\d{2}/\d{2}/\d{4}$'
GROUP BY 1;
CREATE INDEX ON birth_calibration (bucket);

-- 2. provenance columns
--    birth_is_estimated  = the one flag to filter on in code:
--                          FALSE = real looked-up date, TRUE = inferred estimate
ALTER TABLE firm_master
    ADD COLUMN IF NOT EXISTS birth_precision text,
    ADD COLUMN IF NOT EXISTS birth_url text,
    ADD COLUMN IF NOT EXISTS birth_is_estimated boolean;

-- 3. registry births (already have a real incorporation_date): NOT estimated
UPDATE firm_master SET
    birth_is_estimated = false,
    birth_precision = 'day',
    birth_url = 'https://find-and-update.company-information.service.gov.uk/company/' || company_number
WHERE incorporation_date IS NOT NULL AND birth_precision IS NULL;

-- 4. estimate the rest from the company-number sequence: ESTIMATED (flagged)
UPDATE firm_master fm SET
    birth_year         = b.est_year,
    birth_source       = 'estimated_from_company_number',
    birth_precision    = 'year_estimated',
    birth_is_estimated = true,
    birth_url          = NULL
FROM birth_calibration b
WHERE fm.incorporation_date IS NULL
  AND fm.company_number ~ '^[0-9]{8}$'
  AND b.bucket = fm.company_number::bigint / 5000
  AND (fm.birth_precision IS NULL);

-- ============================================================================
-- QA
-- ============================================================================
\echo '--- birth coverage: estimated vs real (filter on birth_is_estimated) ---'
SELECT birth_is_estimated, coalesce(birth_precision,'(none)') AS precision,
       count(*) AS companies
FROM firm_master GROUP BY 1,2 ORDER BY 3 DESC;
\echo '    In code: use "WHERE birth_is_estimated = false" for evidence-grade births only.'

\echo '--- pre-2010 dead firms: births now estimated? ---'
SELECT count(*) AS pre2010_dead,
       count(birth_year) AS with_birth_year
FROM firm_master
WHERE exit_class = 'insolvent' AND death_date < '2010-01-01';

\echo '--- estimated births per year (the newly-filled pre-2010 side) ---'
SELECT birth_year, count(*) FROM firm_master
WHERE birth_precision='year_estimated' AND birth_year BETWEEN 1990 AND 2010
GROUP BY 1 ORDER BY 1;
