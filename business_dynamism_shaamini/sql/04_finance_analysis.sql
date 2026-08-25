-- ============================================================================
-- 04_finance_analysis.sql  —  basic financial profile of insolvent firms
-- Run:  psql companies_house_v2 -P pager=off -f 04_finance_analysis.sql
-- Produces the numbers to drop into findings.html. Uses the firm_master
-- snapshot (pre-death accounts for exits, latest accounts for trading firms).
-- ============================================================================

\echo '--- A. financial profile: insolvent vs solvent vs still-trading ---'
SELECT
    CASE WHEN exit_class = 'insolvent'      THEN '1 insolvent'
         WHEN exit_class = 'solvent'        THEN '2 solvent wind-up'
         ELSE                                    '3 still trading' END          AS grp,
    count(*)                                                                    AS companies,
    count(total_assets)                                                         AS with_accounts,
    round(percentile_cont(0.5) within group (order by total_assets)
          FILTER (WHERE total_assets IS NOT NULL)::numeric)                     AS median_total_assets,
    round(percentile_cont(0.5) within group (order by net_assets)
          FILTER (WHERE net_assets IS NOT NULL)::numeric)                       AS median_net_assets,
    round(percentile_cont(0.5) within group (order by employees)
          FILTER (WHERE employees IS NOT NULL)::numeric)                        AS median_employees,
    round(100.0*count(*) FILTER (WHERE net_assets_negative)
          / nullif(count(net_assets),0), 1)                                     AS pct_negative_net_assets
FROM firm_master
WHERE has_pre_death_accounts OR match_status = 'alive_no_exit'
GROUP BY 1 ORDER BY 1;

\echo '--- B. size mix of insolvencies (share of insolvent firms by size band) ---'
SELECT coalesce(size_class,'(unknown)') AS size_class,
       count(*) AS insolvent_firms,
       round(100.0*count(*)/sum(count(*)) over (), 1) AS pct
FROM firm_master
WHERE exit_class = 'insolvent' AND has_pre_death_accounts
GROUP BY 1 ORDER BY 2 DESC;

\echo '--- C. median total assets of insolvent firms, by year of insolvency ---'
SELECT extract(year from death_date)::int AS year,
       count(total_assets) AS firms_with_accounts,
       round(percentile_cont(0.5) within group (order by total_assets)
             FILTER (WHERE total_assets IS NOT NULL)::numeric) AS median_total_assets
FROM firm_master
WHERE exit_class = 'insolvent' AND has_pre_death_accounts
      AND death_date >= '2008-01-01'
GROUP BY 1 ORDER BY 1;
