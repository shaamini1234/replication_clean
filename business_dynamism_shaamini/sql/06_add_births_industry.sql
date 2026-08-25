-- ============================================================================
-- 06_add_births_industry.sql  —  add the BIRTH leg + industry
-- Run:  psql business_dynamism -f 06_add_births_industry.sql
--
-- Enriches firm_master with, from the CH companies snapshot (joined on company
-- number): real incorporation date (BIRTH), industry (SIC), and current status.
-- This completes business dynamism: births (incorporation) + deaths (insolvency)
-- in one firm-level table.
--
-- Survivorship caveat: the companies snapshot holds only firms currently on the
-- register, so real incorporation dates land for survivors; companies that
-- already died keep the first-filing proxy (birth_source stays 'first_filing').
-- Safe to re-run.
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_companies_num ON companies ("CompanyNumber");

ALTER TABLE firm_master
    ADD COLUMN IF NOT EXISTS incorporation_date date,
    ADD COLUMN IF NOT EXISTS birth_year         int,
    ADD COLUMN IF NOT EXISTS sic_code           text,
    ADD COLUMN IF NOT EXISTS sic_desc           text,
    ADD COLUMN IF NOT EXISTS company_status     text;

UPDATE firm_master f SET
    incorporation_date = CASE WHEN c."IncorporationDate" ~ '^\d{2}/\d{2}/\d{4}$'
                              THEN to_date(c."IncorporationDate", 'DD/MM/YYYY') END,
    birth_year         = CASE WHEN c."IncorporationDate" ~ '^\d{2}/\d{2}/\d{4}$'
                              THEN extract(year from to_date(c."IncorporationDate",'DD/MM/YYYY'))::int END,
    sic_code           = nullif(split_part(c."SICCode_SicText_1", ' - ', 1), ''),
    sic_desc           = nullif(split_part(c."SICCode_SicText_1", ' - ', 2), ''),
    company_status     = c."CompanyStatus"
FROM companies c
WHERE c."CompanyNumber" = f.company_number;

UPDATE firm_master SET birth_source = 'registry' WHERE incorporation_date IS NOT NULL;

-- ============================================================================
-- QA OUTPUT
-- ============================================================================
\echo '--- birth coverage: how many firms now have a real incorporation date ---'
SELECT birth_source, count(*) AS companies,
       round(100.0*count(*)/sum(count(*)) over (),1) AS pct
FROM firm_master GROUP BY 1 ORDER BY 2 DESC;

\echo '--- BIRTHS per year (company incorporations, from the live register) ---'
\echo '    NOTE: survivorship-biased for older years (dead firms have left the register)'
SELECT extract(year from to_date("IncorporationDate",'DD/MM/YYYY'))::int AS birth_year,
       count(*) AS incorporations
FROM companies
WHERE "IncorporationDate" ~ '^\d{2}/\d{2}/\d{4}$'
  AND extract(year from to_date("IncorporationDate",'DD/MM/YYYY')) BETWEEN 2008 AND 2026
GROUP BY 1 ORDER BY 1;

\echo '--- which industries fail most? top 10 SIC among insolvent firms ---'
SELECT coalesce(sic_desc,'(unknown)') AS industry,
       count(*) AS insolvencies
FROM firm_master
WHERE exit_class = 'insolvent' AND sic_desc IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
