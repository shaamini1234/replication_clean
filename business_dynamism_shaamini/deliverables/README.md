# Deliverables — one CSV per parameter

## FTSE (deliverables/ftse/)
- financials: ftse_revenue, ftse_net_income, ftse_total_assets (company_number,ticker,fiscal_year,value,currency,source_url)
- market: ftse_share_price, ftse_dividend, ftse_market_cap, ftse_shares_outstanding (company_number,company_name,year,value,source_url)
- spine: ftse_spine (identity), ftse_birth (legal + operating birth, audited)

## S&P (deliverables/sp500/)
- financials: sp500_revenue, sp500_net_income, sp500_total_assets, sp500_shares_outstanding, sp500_market_cap, sp500_employees (symbol,cik,fiscal_year,value,source_url)
- spine: sp500_spine (identity), sp500_founding (founding dates)

Each parameter file contains only rows where the value exists. Every value has a source_url where one is recorded.
Rebuild: python3 python/build_parameter_csvs.py (reads the newest central DuckDB).