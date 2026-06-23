from dataclasses import dataclass
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Legacy types (used by reporting/ and risk/ modules)
# ---------------------------------------------------------------------------

@dataclass
class EconomicSeries:
    """Economic benchmark data for a calendar year."""
    year: int
    real_gdp_growth: float
    nominal_gdp_growth: float
    cpi_inflation: float
    rpi_inflation: float
    gdp_deflator: float
    unemployment_rate: float
    employment_level: float  # millions
    wages_and_salaries: float  # £bn
    productivity_growth_cumulative: float
    labour_supply_growth: float


@dataclass
class PolicyMeasure:
    """Policy scorekeeping."""
    name: str
    start_year: int
    fiscal_impact_bn: Dict[int, float]
    uncertainty_rating: str
    labour_supply_impact: float = 0.0
    potential_output_impact: float = 0.0


@dataclass
class ExpenditureBreakdown:
    """DEL/AME spending breakdown for a fiscal year."""
    fiscal_year: str  # "2024-25"
    rdel_total: float  # £bn
    cdel_total: float  # £bn
    ame_total: float  # £bn
    debt_interest_spending: float  # £bn


# ---------------------------------------------------------------------------
# New types matched to OBR publications
# ---------------------------------------------------------------------------

@dataclass
class FiscalAggregates:
    """
    Components of net borrowing from OBR Aggregates Table 6.5.
    All values in £ billion.
    """
    fiscal_year: str  # "2024-25"
    current_receipts: float  # PSCR
    current_expenditure: float  # PSCE
    depreciation: float  # DEP
    current_budget_surplus: float  # PSCB = PSCR - PSCE - DEP
    gross_investment: float
    net_investment: float  # PSNI = gross - DEP
    net_borrowing: float  # PSNB = -PSCB + PSNI
    nominal_gdp: Optional[float] = None
    psnb_pct_gdp: Optional[float] = None
    psnd_pct_gdp: Optional[float] = None


@dataclass
class GDPComponents:
    """GDP from expenditure side, quarterly, £bn chain-linked volumes."""
    date: str  # "2024Q1"
    private_consumption: float
    government_consumption: float
    fixed_investment: float
    business_investment: float
    private_dwellings: float
    general_government_investment: float
    change_in_inventories: float
    exports: float
    imports: float
    gdp: float
    valuables: float = 0.0
    total_final_expenditure: float = 0.0
    statistical_discrepancy: float = 0.0
    non_oil_gva: float = 0.0


@dataclass
class GDPIncomeComponents:
    """GDP from income side, quarterly, £bn nominal."""
    date: str
    labour_income: float
    non_oil_pnfc_profits: float
    other_income: float
    gva_factor_cost: float
    taxes_on_products_less_subsidies: float
    statistical_discrepancy: float
    gdp_market_prices: float


@dataclass
class LabourMarket:
    """Labour market indicators, quarterly, from Economy Table 1.6."""
    date: str
    employment_millions: float
    employment_rate: float
    unemployment_millions: float
    unemployment_rate: float
    participation_rate: float
    average_hours: float
    total_hours_millions: float
    compensation_of_employees: float
    employees_millions: float = 0.0      # ES — employees (excl. self-employed)
    wages_salaries_bn: float = 0.0       # WFJ — wages and salaries £bn
    awe_index: float = 0.0               # PSAVEI — average weekly earnings index


@dataclass
class MarketAssumptions:
    """Market conditioning assumptions, quarterly, from Economy Table 1.9."""
    date: str  # "2024Q1"
    bank_rate: float
    gilt_yield_20y: float
    average_mortgage_rate: Optional[float] = None
    exchange_rate_eri: Optional[float] = None
    oil_price_usd: Optional[float] = None
    deposit_rate: Optional[float] = None
    usd_exchange_rate: Optional[float] = None
    equity_prices: Optional[float] = None


@dataclass
class ReceiptsBreakdown:
    """Detailed tax receipts from Receipts tables, annual fiscal year, £bn."""
    fiscal_year: str
    income_tax_gross: float
    national_insurance: float
    vat: float
    corporation_tax: float
    fuel_duties: float
    business_rates: float
    council_tax: float
    other_taxes: float
    non_tax_receipts: float
    total_current_receipts: float


@dataclass
class NominalGDPComponents:
    """GDP from expenditure side, quarterly, £bn current prices (Economy Table 1.2)."""
    date: str
    private_consumption: float       # CONSPS
    government_consumption: float    # CGGPS
    fixed_investment: float          # IFPS
    general_government_investment: float  # GGIPS
    valuables: float                 # VALPS
    change_in_inventories: float     # DINVPS
    exports: float                   # XPS
    total_final_expenditure: float   # TFEPS
    imports: float                   # MPS
    statistical_discrepancy: float   # SDEPS
    gdp_market_prices: float         # GDPMPS


@dataclass
class PriceIndices:
    """Price index levels, quarterly (Economy Table 1.7)."""
    date: str
    rpi: float    # Jan 1987=100
    cpi: float    # 2015=100
    cpih: float   # 2015=100
    ooh: float    # 2015=100
    pce: float    # 2022=100 (consumer expenditure deflator)
    pgdp: float   # 2022=100 (GDP deflator)


@dataclass
class DebtInterest:
    """Central government debt interest from Aggregates Table 6.16, £bn."""
    fiscal_year: str
    conventional_gilts: float
    apf_gilts: float  # BoE Asset Purchase Facility
    index_linked_gilts: float
    ns_and_i: float
    other: float
    total: float  # net of APF


@dataclass
class DetailedReceipts:
    """Granular tax receipts from Receipts Table 3.9, annual fiscal year, £bn.
    Maps individual tax lines to Winsolve variable names where known."""
    fiscal_year: str
    income_tax_gross: float       # Row 7 — model splits into TYEM + TSEOP
    paye: float                   # Row 9 (sub-item)
    self_assessment: float        # Row 10 (sub-item)
    national_insurance: float     # Row 12 — model splits into EENIC + EMPNIC
    vat: float                    # Row 13 — VREC
    corporation_tax: float        # Row 14 — CT
    petroleum_revenue_tax: float  # Row 20 — PRT
    fuel_duties: float            # Row 21 — TXFUEL
    capital_gains_tax: float      # Row 22 — CGT
    inheritance_tax: float        # Row 23 — INHT
    sdlt: float                   # Row 24
    ated: float                   # Row 25
    stamp_taxes_shares: float     # Row 26
    tobacco_duties: float         # Row 27 — TXTOB
    alcohol_duties: float         # Rows 28-30 sum — TXALC
    air_passenger_duty: float     # Row 31
    insurance_premium_tax: float  # Row 32 — IPT
    climate_change_levy: float    # Row 33 — CCL
    landfill_tax: float           # Row 34
    customs_duties: float         # Row 37 — TXCUS
    apprenticeship_levy: float    # Row 42
    energy_profits_levy: float    # Row 46
    total_hmrc: float             # Row 51
    vehicle_excise_duties: float  # Row 52
    business_rates: float         # Row 53 — NNDRA
    council_tax: float            # Row 54 — CC
    vat_refunds: float            # Row 55
    interest_and_dividends: float  # Row 58
    gross_operating_surplus: float  # Row 62
    other_receipts: float         # Row 63
    total_current_receipts: float  # Row 64 — PSCR


@dataclass
class HouseholdIncome:
    """Household disposable income, quarterly, £bn (Economy Table 1.12).
    Data from 2012Q1 onwards."""
    date: str
    labour_income: float
    employee_compensation: float     # FYEMP (also in 1.6)
    mixed_income: float              # MI
    employer_social_contributions: float  # EMPSC
    non_labour_income: float
    net_benefits_taxes: float
    household_disposable_income: float  # HHDI


@dataclass
class BalanceOfPayments:
    """Balance of payments, quarterly, £bn (Economy Table 1.8).
    Data from 2008Q1 onwards."""
    date: str
    trade_balance: float                 # TB
    trade_balance_pct_gdp: float
    investment_income_balance: float     # NIPD
    employee_income_balance: float
    transfers_balance: float             # TRANB
    current_account_balance: float       # CB
    current_account_pct_gdp: float       # CBPCNT


@dataclass
class HouseholdBalanceSheet:
    """Household balance sheet, quarterly, £bn (Economy Table 1.11).
    Data from 2012Q1 onwards."""
    date: str
    physical_assets: float       # APH
    financial_assets: float      # GFWPE
    total_liabilities: float
    secured_liabilities: float   # LHP (mortgage stock)
    other_liabilities: float     # OLPE
    total_net_worth: float


@dataclass
class OutputGap:
    """OBR central estimate of the output gap, quarterly % (Economy Table 1.14).
    Data from 1972Q1 onwards."""
    date: str
    output_gap_pct: float        # GAP = GDPM/TRGDP*100 - 100


@dataclass
class PotentialOutput:
    """Potential output forecast, quarterly (Economy Table 1.15).
    Data from 2019Q1 onwards."""
    date: str
    potential_output_bn: float   # TRGDP (converted from £m to £bn)
    population_16plus_mn: float  # POP16 (converted from thousands to millions)
    nairu: float                 # equilibrium unemployment rate
    potential_emp_rate: float
    potential_avg_hours: float
    potential_productivity: float
