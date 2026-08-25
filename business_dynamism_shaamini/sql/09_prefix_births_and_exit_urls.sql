-- ============================================================================
-- 09_prefix_births_and_exit_urls.sql
-- Run:  psql business_dynamism -f 09_prefix_births_and_exit_urls.sql
--
-- Part A: estimate birth YEAR for SC / NI / OC / etc. prefixed firms (Scotland,
--         Northern Ireland, LLPs) — each prefix has its own sequential number
--         space, so we calibrate number->year per prefix. Same honest tagging:
--         birth_is_estimated = true, year precision, no source URL.
--
-- Part B: give every EXIT a source URL. Insolvency/solvent exits come from The
--         Gazette, so exit_url = the death-event notice page. exit_is_estimated
--         = false (these are looked-up facts with day precision).
--         (Strike-off exits from the CH API get their CH URL when that data is
--          merged in later — the extraction is still running.)
-- Safe to re-run.
-- ============================================================================

-- ---- Part A: prefixed births ----------------------------------------------
DROP TABLE IF EXISTS birth_calibration_prefix;
CREATE TABLE birth_calibration_prefix AS
SELECT left("CompanyNumber",2) AS prefix,
       (substring("CompanyNumber" from 3)::int / 1000) AS bucket,
       round(percentile_cont(0.5) within group (
           order by extract(year from to_date("IncorporationDate",'DD/MM/YYYY'))))::int AS est_year
FROM companies
WHERE "CompanyNumber" ~ '^[A-Z]{2}[0-9]{6}$'
  AND "IncorporationDate" ~ '^\d{2}/\d{2}/\d{4}$'
GROUP BY 1,2;
CREATE INDEX ON birth_calibration_prefix (prefix, bucket);

UPDATE firm_master fm SET
    birth_year         = b.est_year,
    birth_source       = 'estimated_from_company_number',
    birth_precision    = 'year_estimated',
    birth_is_estimated = true,
    birth_url          = NULL
FROM birth_calibration_prefix b
WHERE fm.birth_precision IS NULL
  AND fm.company_number ~ '^[A-Z]{2}[0-9]{6}$'
  AND b.prefix  = left(fm.company_number,2)
  AND b.bucket  = substring(fm.company_number from 3)::int / 1000;

-- ---- Part B: exit source URLs (Gazette death notice) -----------------------
ALTER TABLE firm_master
    ADD COLUMN IF NOT EXISTS exit_url text,
    ADD COLUMN IF NOT EXISTS exit_precision text,
    ADD COLUMN IF NOT EXISTS exit_is_estimated boolean;

UPDATE firm_master fm SET
    exit_url = 'https://www.thegazette.co.uk/notice/' || sub.notice_id,
    exit_precision = 'day',
    exit_is_estimated = false
FROM (
    SELECT DISTINCT ON (cn, event_date) cn, event_date, notice_id
    FROM (
        SELECT CASE WHEN company_number ~ '^[0-9]{1,8}$' THEN lpad(company_number,8,'0')
                    ELSE upper(trim(company_number)) END AS cn,
               event_date, notice_id
        FROM gazette_events
    ) x
    ORDER BY cn, event_date, notice_id
) sub
WHERE fm.exit_observed
  AND sub.cn = fm.company_number
  AND sub.event_date = fm.death_date
  AND fm.exit_url IS NULL;

-- ============================================================================
-- QA
-- ============================================================================
\echo '--- births now: real vs estimated vs still unknown ---'
SELECT coalesce(birth_is_estimated::text,'(no birth)') AS is_estimated,
       count(*) FROM firm_master GROUP BY 1 ORDER BY 2 DESC;

\echo '--- exits with a source URL (of all observed exits) ---'
SELECT count(*) FILTER (WHERE exit_observed)              AS exits,
       count(*) FILTER (WHERE exit_url IS NOT NULL)       AS with_source_url,
       round(100.0*count(*) FILTER (WHERE exit_url IS NOT NULL)
             / nullif(count(*) FILTER (WHERE exit_observed),0),1) AS pct
FROM firm_master;

\echo '--- sample: a company with full provenance (birth + exit) ---'
SELECT company_number, birth_year, birth_is_estimated, birth_url,
       death_date, exit_url
FROM firm_master
WHERE exit_url IS NOT NULL AND birth_is_estimated = false
LIMIT 3;
