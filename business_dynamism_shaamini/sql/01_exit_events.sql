-- ============================================================================
-- 01_exit_events.sql  —  Step 1 of the combined build
-- Run locally:  psql companies_house -f 01_exit_events.sql
--
-- Builds:
--   gazette_norm   : gazette_events + normalised company number + key_status
--   exit_events    : one row per company's insolvency/exit (deaths collapsed)
-- Then prints QA: key validity, exit-class mix, and the Gazette->CH match rate.
--
-- NOTE: CH financial_filings only covers 2008 onward (electronic filing began
-- then). A death before 2008 CANNOT match to accounts by construction, so the
-- match-rate QA reports both the raw figure and the fair one (deaths >= 2008).
--
-- Local gazette_events schema (slim): notice_id, event_type, company_number,
-- company_name, event_date.  Safe to re-run: rebuilds derived tables only.
-- ============================================================================

-- ---- 1. Normalise the join key, flag invalid ones --------------------------
DROP TABLE IF EXISTS gazette_norm;
CREATE TABLE gazette_norm AS
SELECT
    notice_id,
    event_type,
    event_date,
    company_name,
    company_number                                   AS company_number_raw,
    CASE
        WHEN company_number ~ '^[0-9]{1,8}$'
            THEN lpad(company_number, 8, '0')        -- zero-pad numeric to 8
        ELSE upper(trim(company_number))             -- SC/NI/OC… prefixes as-is
    END                                              AS company_number_norm
FROM gazette_events
WHERE company_number IS NOT NULL;

ALTER TABLE gazette_norm ADD COLUMN key_status text;
UPDATE gazette_norm SET key_status =
    CASE WHEN company_number_norm ~ '^[0-9]{8}$'
           OR company_number_norm ~ '^[A-Z]{2}[0-9]{6}$'
         THEN 'valid' ELSE 'invalid' END;

CREATE INDEX ON gazette_norm (company_number_norm);

-- ---- 2. Classify notice types into exit semantics --------------------------
DROP TABLE IF EXISTS gazette_classified;
CREATE TABLE gazette_classified AS
SELECT *,
    CASE event_type
        WHEN 'creditors_voluntary_winding_up'  THEN 'insolvent'
        WHEN 'winding_up_order_court'          THEN 'insolvent'
        WHEN 'administration'                  THEN 'insolvent'
        WHEN 'administrative_receivership'     THEN 'insolvent'
        WHEN 'members_voluntary_winding_up'    THEN 'solvent'
        WHEN 'petition_to_wind_up'             THEN 'threat'
        WHEN 'removed_from_register'           THEN 'administrative'
        WHEN 'restored_to_register'            THEN 'administrative'
        ELSE 'other'
    END AS event_class
FROM gazette_norm;

-- ---- 3. Collapse to one exit row per company -------------------------------
DROP TABLE IF EXISTS exit_events;
CREATE TABLE exit_events AS
WITH terminal AS (
    SELECT * FROM gazette_classified
    WHERE key_status = 'valid' AND event_class IN ('insolvent','solvent')
),
first_terminal AS (
    SELECT DISTINCT ON (company_number_norm)
        company_number_norm,
        event_date  AS death_date,
        event_type  AS exit_type,
        event_class AS exit_class,
        company_name
    FROM terminal
    ORDER BY company_number_norm, event_date, notice_id
),
agg AS (
    SELECT
        company_number_norm,
        count(*) FILTER (WHERE event_class IN ('insolvent','solvent')) AS n_terminal_notices,
        bool_or(event_class = 'threat')                                 AS had_prior_petition,
        min(event_date)                                                 AS first_notice_date,
        max(event_date)                                                 AS last_notice_date
    FROM gazette_classified
    WHERE company_number_norm IN (SELECT company_number_norm FROM terminal)
    GROUP BY company_number_norm
)
SELECT
    f.company_number_norm,
    f.death_date,
    f.exit_type,
    f.exit_class,
    f.company_name,
    a.n_terminal_notices,
    a.had_prior_petition,
    a.first_notice_date,
    a.last_notice_date
FROM first_terminal f JOIN agg a USING (company_number_norm);

CREATE INDEX ON exit_events (company_number_norm);

-- ============================================================================
-- QA OUTPUT
-- ============================================================================
\echo '--- key validity (distinct companies) ---'
SELECT key_status, count(DISTINCT company_number_norm) AS companies
FROM gazette_norm GROUP BY key_status ORDER BY 2 DESC;

\echo '--- exit_events: rows and class mix ---'
SELECT exit_class, count(*) AS companies,
       min(death_date) AS earliest, max(death_date) AS latest
FROM exit_events GROUP BY exit_class ORDER BY 2 DESC;

\echo '--- MATCH RATE (raw, all years) ---'
SELECT
    count(*)                                              AS exit_companies,
    count(*) FILTER (WHERE ff.company_number IS NOT NULL) AS matched,
    round(100.0 * count(*) FILTER (WHERE ff.company_number IS NOT NULL)
          / count(*), 1)                                  AS pct_matched
FROM exit_events e
LEFT JOIN (SELECT DISTINCT company_number FROM financial_filings) ff
       ON ff.company_number = e.company_number_norm;

\echo '--- MATCH RATE (fair: deaths 2008+, where CH accounts can exist) ---'
SELECT
    count(*)                                              AS exit_companies_2008plus,
    count(*) FILTER (WHERE ff.company_number IS NOT NULL) AS matched,
    round(100.0 * count(*) FILTER (WHERE ff.company_number IS NOT NULL)
          / count(*), 1)                                  AS pct_matched
FROM exit_events e
LEFT JOIN (SELECT DISTINCT company_number FROM financial_filings) ff
       ON ff.company_number = e.company_number_norm
WHERE e.death_date >= '2008-01-01';

\echo '--- match rate by exit_class (deaths 2008+) ---'
SELECT e.exit_class,
       count(*) AS companies,
       round(100.0 * count(*) FILTER (WHERE ff.company_number IS NOT NULL)
             / count(*), 1) AS pct_matched
FROM exit_events e
LEFT JOIN (SELECT DISTINCT company_number FROM financial_filings) ff
       ON ff.company_number = e.company_number_norm
WHERE e.death_date >= '2008-01-01'
GROUP BY e.exit_class ORDER BY 2 DESC;
