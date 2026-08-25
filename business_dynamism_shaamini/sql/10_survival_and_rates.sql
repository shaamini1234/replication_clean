-- ============================================================================
-- 10_survival_and_rates.sql — business-dynamism analysis: how firms fail
-- Run:  psql business_dynamism -f 10_survival_and_rates.sql
--
-- Uses firm_master (now has birth_year + death_date + exit_class + sic + size).
-- HONEST SCOPE: firm_master = firms that filed accounts OR had an insolvency.
-- It excludes never-filed survivors, so absolute rates here read a bit high vs
-- the whole register — treat these as risk patterns among *observed* firms, and
-- lean on the age/industry/size *contrasts* (which are robust) rather than the
-- absolute levels. Insolvent = distress deaths only (MVL/solvent excluded).
-- ============================================================================

\echo '--- A. How old are firms when they become insolvent? (age = death yr - birth yr) ---'
SELECT (death_year - birth_year) AS age_at_insolvency, count(*) AS firms
FROM (SELECT extract(year from death_date)::int death_year, birth_year
      FROM firm_master
      WHERE exit_class='insolvent' AND birth_year IS NOT NULL AND death_date IS NOT NULL) t
WHERE (death_year - birth_year) BETWEEN 0 AND 25
GROUP BY 1 ORDER BY 1;

\echo '--- B. median age at insolvency, by decade of death ---'
SELECT (extract(year from death_date)::int/10*10) AS death_decade,
       count(*) AS insolvencies,
       round(percentile_cont(0.5) within group
             (order by extract(year from death_date)::int - birth_year)) AS median_age
FROM firm_master
WHERE exit_class='insolvent' AND birth_year IS NOT NULL AND death_date >= '2000-01-01'
GROUP BY 1 ORDER BY 1;

\echo '--- C. insolvency rate by industry (top 12 sectors by firm count) ---'
SELECT sic_desc,
       count(*) AS firms,
       count(*) FILTER (WHERE exit_class='insolvent') AS insolvent,
       round(100.0*count(*) FILTER (WHERE exit_class='insolvent')/count(*),1) AS pct_insolvent
FROM firm_master
WHERE sic_desc IS NOT NULL
GROUP BY 1 HAVING count(*) > 20000
ORDER BY pct_insolvent DESC LIMIT 12;

\echo '--- D. insolvency rate by size band ---'
SELECT coalesce(size_class,'(unknown)') AS size_class,
       count(*) AS firms,
       round(100.0*count(*) FILTER (WHERE exit_class='insolvent')/count(*),1) AS pct_insolvent
FROM firm_master GROUP BY 1 ORDER BY 2 DESC;

\echo '--- E. cohort hazard: of firms born in year C, % insolvent within 5 years ---'
SELECT birth_year AS cohort,
       count(*) AS born,
       count(*) FILTER (WHERE exit_class='insolvent'
             AND extract(year from death_date)::int - birth_year <= 5) AS insolvent_by_5yr,
       round(100.0*count(*) FILTER (WHERE exit_class='insolvent'
             AND extract(year from death_date)::int - birth_year <= 5)/count(*),1) AS pct_5yr
FROM firm_master
WHERE birth_year BETWEEN 2008 AND 2019     -- cohorts old enough to observe 5 years
GROUP BY 1 ORDER BY 1;
