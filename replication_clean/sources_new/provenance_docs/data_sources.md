# Data Sources Reference

This document inventories repository data assets and records verifiable structure, coverage, and provenance signals based on direct file/header inspection.

## data

**Location**
data/Aggregates_Detailed_forecast_tables_March_2025.xlsx, data/Aggregates_Detailed_forecast_tables_November_2025.xlsx, data/CBP_proposals.csv, data/Changes to departmental spending at the upcoming Budget _ Institute for Fiscal Studies.pdf, data/Debt_interest_Detailed_forecast_tables_March_2025.xlsx, data/Debt_interest_Detailed_forecast_tables_November_2025.xlsx, data/Economic and fiscal outlook - March 2025.pdf, data/Economy_Detailed_forecast_tables_March_2025.xlsx, data/Economy_Detailed_forecast_tables_November_2025.xlsx, data/Expenditure_Detailed_forecast_tables_March_2025.xlsx, data/Expenditure_Detailed_forecast_tables_November_2025.xlsx, data/Final_print_HMT_Budget_2025_TEXT_PRINT_NEW.pdf, data/Fiscal Rules Explainer.pdf, data/Fiscal_forecast_revisions_database_March_2025.xlsx, data/Forecast-evaluation-report-–-July-2025-annex-A-–-supplementary-economy-tables.xlsx, data/Forecast-evaluation-report-–-July-2025-annex-B-–-supplementary-fiscal-tables.xlsx, data/Forecast-evaluation-report-–-July-2025-char-ts-and-tables.xlsx, data/Long-term-economic-determinants-March-2025-EFO.xlsx, data/March_2025_Economic_and_fiscal_outlook_ready_reckoner.xlsx, data/NS_Table.ods, data/OBR_Economic_and_fiscal_outlook_November_2025.pdf, data/PSF_aggregates_databank_Nov-EFO.xlsx, data/PSF_aggregates_databank_Oct-4.xlsx, data/Policy_Detailed_forecast_tables_March_2025.xlsx, data/Policy_measures_database_March_2025.xlsx, data/Public sector finances, UK - October 2025.pdf, data/Receipts_Detailed_forecast_tables_March_2025.xlsx, data/Receipts_Detailed_forecast_tables_November_2025.xlsx, data/The IFS GreenBudget - October 2025.pdf, data/Uncertainty_ratings_database_March_2025.xlsx, data/Welfare-trends-report-October-2024-charts-and-tables.xlsx, data/Yield from British Government Securities, 20 year Nominal Par Yield.csv, data/employment.csv, data/fiscal_decomposition.csv, data/gdp.csv, ... (11 more files)

**Source**
Office for Budget Responsibility (OBR); Office for Budget Responsibility (OBR), Economic and Fiscal Outlook; Institute for Fiscal Studies (IFS); Institute for Fiscal Studies (IFS), Green Budget

**Description**
31 spreadsheet file(s); sample sheets from `data/Aggregates_Detailed_forecast_tables_March_2025.xlsx`: Contents, Aggregates, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6 7 .csv file(s); sample schema from `data/CBP_proposals.csv`: Proposal, 2026 (Year 1), 2027 (Year 2), 2028 (Year 3), 2029 (Year 4), 2030 (Year 5); rows=16 7 PDF reference/report file(s) 1 spreadsheet file(s); sample sheets from `data/NS_Table.ods`: sheet names unavailable

**Coverage**
- Time: Filename years observed: 2024 to 2025
- Geography: Not explicit in inspected headers/keys.
- Unit of observation: Time-indexed observations appear present.

**Caveats**
No additional source-specific caveat identified beyond cross-cutting caveats.


## data/sectoral_productivity

**Location**
data/sectoral_productivity/UK_Prod.R, data/sectoral_productivity/gdpolowlevelaggregates2022q4.xlsx, data/sectoral_productivity/rGDP.csv

**Source**
Not explicitly identifiable from local file metadata; verify against project ingestion notes/scripts.

**Description**
1 .r file(s) 1 spreadsheet file(s); sample sheets from `data/sectoral_productivity/gdpolowlevelaggregates2022q4.xlsx`: Cover_sheet, Table_of_contents, Notes, 1, 2a, Transpose, Sheet2, 2b 1 .csv file(s); sample schema from `data/sectoral_productivity/rGDP.csv`: Time period and dataset code row, Total GVA, A; rows=349

**Coverage**
- Time: Filename years observed: 2022 to 2022
- Geography: Not explicit in inspected headers/keys.
- Unit of observation: Time-indexed observations appear present.

**Caveats**
Provider/publication is not explicit in local metadata for this source group; verify provenance from ingestion scripts/notes before citation.


## Cross-Cutting Caveats

- Source attribution can be incomplete when provider/publication metadata is absent from local files; confirm against acquisition logs, scripts, or citations before publication use.
- Coverage summaries rely on inspected headers, sheet names, keys, and filename date patterns; validate against canonical source documentation for final claims.
- Mixed file formats and vintages can introduce schema drift and crosswalk inconsistencies; validate joins and harmonization assumptions before pooled analysis.
- Descriptive and predictive associations in these datasets do not establish causal effects without explicit identification design.

