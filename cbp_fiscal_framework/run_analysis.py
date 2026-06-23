"""
CBP Fiscal Framework — main analysis entry point.

Usage:
    python3 run_analysis.py              # loads March 2026 (default)
    python3 run_analysis.py 2025-03      # loads March 2025
    python3 run_analysis.py 2025-11      # loads November 2025
    python3 run_analysis.py all          # loads and compares all vintages
"""

import logging
import os
import sys

# Add parent directory so package imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from cbp_fiscal_framework.inputs.data_manager import DataManager
from cbp_fiscal_framework.core.winsolve import (
    build_model_state, build_model_state_from_db, validate_equations,
    IdentitySolver, solve_equation,
)
from cbp_fiscal_framework.db.timeseries_db import TimeSeriesDB

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

AVAILABLE_VINTAGES = ['2025-03', '2025-11', '2026-03']


def load_vintage(vintage: str) -> DataManager:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, '..', 'data', vintage, 'obr')

    if not os.path.isdir(data_dir):
        logger.error("Data directory not found: %s", data_dir)
        sys.exit(1)

    dm = DataManager()
    dm.register_obr_vintage(data_dir)

    model_path = os.path.join(base_dir, '..', 'docs', 'Macroeconomic_model_code_March_2025.txt')
    if os.path.isfile(model_path):
        dm.register_model_code(model_path)

    dm.load_all_data()
    return dm


def print_economy_summary(dm: DataManager):
    gdp = dm.get_data('gdp_components')
    income = dm.get_data('gdp_income')
    labour = dm.get_data('labour_market')
    market = dm.get_data('market_assumptions')

    print(f"\n--- Economy data loaded ---")
    print(f"  GDP expenditure (1.1):    {len(gdp or []):>3} quarters")
    print(f"  GDP income (1.3):         {len(income or []):>3} quarters")
    print(f"  Labour market (1.6):      {len(labour or []):>3} quarters")
    print(f"  Market assumptions (1.9): {len(market or []):>3} quarters")

    if gdp:
        print(f"  Date range: {gdp[0].date} – {gdp[-1].date}")
        latest = gdp[-1]
        print(f"\n  Latest quarter ({latest.date}):")
        print(f"    Real GDP = {latest.gdp:.1f},  C = {latest.private_consumption:.1f},"
              f"  I = {latest.fixed_investment:.1f},  G = {latest.government_consumption:.1f}")
    if market:
        latest = market[-1]
        print(f"    Bank Rate = {latest.bank_rate:.2f}%,"
              f"  20yr gilts = {latest.gilt_yield_20y:.2f}%")


def print_receipts_summary(dm: DataManager):
    receipts = dm.get_data('receipts_breakdown')
    if not receipts:
        return

    print(f"\n--- Receipts breakdown (£bn) ---\n")
    print(f"{'Fiscal Year':<14} {'Inc Tax':>8} {'NICs':>8} {'VAT':>8}"
          f" {'CorpTax':>8} {'Fuel':>6} {'Other':>8} {'Total':>10}")
    print('-' * 84)
    for r in receipts:
        print(f"{r.fiscal_year:<14} {r.income_tax_gross:>8.1f} {r.national_insurance:>8.1f}"
              f" {r.vat:>8.1f} {r.corporation_tax:>8.1f} {r.fuel_duties:>6.1f}"
              f" {r.other_taxes:>8.1f} {r.total_current_receipts:>10.1f}")


def print_debt_interest_summary(dm: DataManager):
    di = dm.get_data('debt_interest')
    if not di:
        return

    print(f"\n--- Debt interest (£bn) ---\n")
    print(f"{'Fiscal Year':<14} {'Convent':>8} {'APF':>8} {'ILG':>8}"
          f" {'NS&I':>6} {'Other':>6} {'Total':>8}")
    print('-' * 64)
    for d in di:
        print(f"{d.fiscal_year:<14} {d.conventional_gilts:>8.1f} {d.apf_gilts:>8.1f}"
              f" {d.index_linked_gilts:>8.1f} {d.ns_and_i:>6.1f}"
              f" {d.other:>6.1f} {d.total:>8.1f}")


def print_model_summary(dm: DataManager):
    model = dm.get_data('model')
    if not model:
        return
    print()
    print(model.summary())


def print_topology(dm: DataManager):
    model = dm.get_data('model')
    if not model:
        return
    from cbp_fiscal_framework.core.winsolve import IdentitySolver
    solver = IdentitySolver(model)
    print()
    print(solver.topology_summary())


def print_validation_report(dm: DataManager):
    model = dm.get_data('model')
    if not model:
        return

    state, mapping_report = build_model_state(dm)
    loaded = mapping_report['loaded']
    skipped = mapping_report['skipped']
    print(f"\n--- Variable Mapping ---")
    print(f"  Loaded: {len(loaded)} / {len(loaded) + len(skipped)} mapped variables")
    print(f"  Dates: {mapping_report['total_dates']} quarters ({mapping_report['date_range']})")
    if skipped:
        print(f"  Skipped: {', '.join(f'{v} ({r})' for v, r in skipped[:5])}")

    report = validate_equations(model, state)
    print(f"\n--- Equation Validation ---")
    print(f"  Equations tested: {report.tested_equations} / "
          f"{report.tested_equations + report.skipped_equations} testable")
    print(f"  Passed: {report.passed_equations},  Failed: {report.failed_equations},  "
          f"Skipped: {report.skipped_equations}")
    print(f"  Period checks: {report.passed_checks} / {report.total_checks} passed")

    if report.per_equation:
        print(f"\n  {'Variable':<12} {'Result':>6} {'Periods':>10} {'Max Resid':>12}  Equation")
        print(f"  {'-'*62}")
        for var in sorted(report.per_equation):
            info = report.per_equation[var]
            status = 'PASS' if info['passed'] == info['tested'] else 'FAIL'
            print(f"  {var:<12} {status:>6} {info['passed']:>4}/{info['tested']:<4}"
                  f" {info['max_residual']:>12.4f}  {info['raw']}")

    if report.skip_reasons:
        n_show = min(10, len(report.skip_reasons))
        print(f"\n  Skipped ({len(report.skip_reasons)} equations, showing {n_show}):")
        for i, (var, reason) in enumerate(sorted(report.skip_reasons.items())):
            if i >= n_show:
                break
            print(f"    {var:<12} {reason}")


def print_forward_solve(dm: DataManager):
    model = dm.get_data('model')
    if not model:
        return

    state, mapping_report = build_model_state(dm)
    solver = IdentitySolver(model)

    n_dates = len(state.dates)
    # Start from t=1 so that seeded recursive variables (BPA, GGVA, etc.) can
    # propagate from their t=0 seed values before they are needed as lags at t>=2.
    # Equations that need 4-period lags (e.g. LASUBPR) will simply fail for
    # t=1..3 and succeed from t=4 onwards — which is the correct behaviour.
    start_t = 1

    solved_vars = set()
    error_vars = {}  # var -> (first_error_msg, count)

    for t in range(start_t, n_dates):
        state.current_t = t
        for block in solver.blocks:
            if len(block) == 1:
                var = block[0]
                try:
                    eq = solver._identity_eqs[var]
                    value = solve_equation(eq, state)
                    state.set(var, value)
                    solved_vars.add(var)
                except Exception as e:
                    msg = str(e)
                    if var not in error_vars:
                        error_vars[var] = (msg, 0)
                    _, count = error_vars[var]
                    error_vars[var] = (msg, count + 1)
            else:
                try:
                    # Simultaneous block — try Gauss-Seidel
                    solver._solve_simultaneous(block, state)
                    solved_vars.update(block)
                except Exception as e:
                    msg = str(e)
                    for var in block:
                        if var not in error_vars:
                            error_vars[var] = (msg, 0)
                        _, count = error_vars[var]
                        error_vars[var] = (msg, count + 1)

    loaded_vars = set(mapping_report['loaded'])
    newly_computed = sorted(solved_vars - loaded_vars)

    print(f"\n--- Forward Solve ---")
    print(f"  Periods: {start_t} to {n_dates - 1} ({n_dates - start_t} quarters)")
    print(f"  Variables solved: {len(solved_vars)} / {solver.identity_count}")
    print(f"  Newly computed (not in loaded state): {len(newly_computed)}")
    print(f"  Variables with errors: {len(error_vars)}")
    if newly_computed:
        shown = ', '.join(newly_computed[:10])
        suffix = f', ... (+{len(newly_computed)-10})' if len(newly_computed) > 10 else ''
        print(f"  Computed vars: {shown}{suffix}")

    if error_vars:
        # Group errors by message pattern
        by_reason = {}
        for var, (msg, count) in error_vars.items():
            # Extract the core reason
            if 'not in state' in msg:
                missing_var = msg.split("'")[1]
                reason = f"missing '{missing_var}'"
            elif 'is None' in msg:
                reason = 'None value'
            elif 'Division by zero' in msg:
                reason = 'division by zero'
            elif 'out of range' in msg:
                reason = 'index out of range'
            elif 'math domain' in msg.lower():
                reason = 'math domain error'
            else:
                reason = msg[:60]
            by_reason.setdefault(reason, []).append(var)

        print(f"\n  Error summary ({len(by_reason)} distinct reasons):")
        for reason in sorted(by_reason, key=lambda r: -len(by_reason[r])):
            vars_list = sorted(by_reason[reason])
            n = len(vars_list)
            shown = ', '.join(vars_list[:5])
            suffix = f', ... (+{n-5})' if n > 5 else ''
            print(f"    {reason}: {n} vars — {shown}{suffix}")


def print_detailed_receipts(dm: DataManager):
    detailed = dm.get_data('detailed_receipts')
    if not detailed:
        return

    print(f"\n--- Detailed Receipts (£bn) ---")
    # Cross-check: total_hmrc + non-HMRC should equal total_current_receipts
    passed = 0
    tested = 0
    for dr in detailed:
        tested += 1
        non_hmrc = (dr.vehicle_excise_duties + dr.business_rates + dr.council_tax
                    + dr.vat_refunds + dr.interest_and_dividends
                    + dr.gross_operating_surplus + dr.other_receipts)
        # Accruals + ETS + other minor items make up the gap
        computed = dr.total_hmrc + non_hmrc
        residual = abs(dr.total_current_receipts - computed)
        # The gap is the accruals adjustment + ETS line — allow up to 20bn
        if residual < 20.0:
            passed += 1

    print(f"  Fiscal years: {detailed[0].fiscal_year} to {detailed[-1].fiscal_year}")
    print(f"  Cross-check (HMRC + non-HMRC ~ total): {passed}/{tested} within tolerance")

    # Show key tax heads for latest forecast year
    dr = detailed[-1]
    print(f"\n  {dr.fiscal_year} breakdown:")
    print(f"    Income tax (gross):  {dr.income_tax_gross:>8.1f}  (PAYE {dr.paye:.1f}, SA {dr.self_assessment:.1f})")
    print(f"    NICs:                {dr.national_insurance:>8.1f}")
    print(f"    VAT:                 {dr.vat:>8.1f}")
    print(f"    Corporation tax:     {dr.corporation_tax:>8.1f}")
    print(f"    CGT:                 {dr.capital_gains_tax:>8.1f}  IHT: {dr.inheritance_tax:.1f}")
    print(f"    Fuel duties:         {dr.fuel_duties:>8.1f}")
    print(f"    Alcohol + tobacco:   {dr.alcohol_duties + dr.tobacco_duties:>8.1f}")
    print(f"    Council tax:         {dr.council_tax:>8.1f}")
    print(f"    Business rates:      {dr.business_rates:>8.1f}")
    print(f"    Total HMRC:          {dr.total_hmrc:>8.1f}")
    print(f"    Total receipts:      {dr.total_current_receipts:>8.1f}")


def print_fiscal_summary(dm: DataManager, vintage: str):
    aggregates = dm.get_data('fiscal_aggregates')
    if not aggregates:
        print(f"  No fiscal aggregates loaded for {vintage}")
        return

    print(f"\n{'Fiscal Year':<14} {'PSCR':>10} {'PSCE':>10} {'DEP':>8}"
          f" {'PSCB':>10} {'PSNI':>8} {'PSNB':>10}")
    print('-' * 76)
    for fa in aggregates:
        print(f"{fa.fiscal_year:<14} {fa.current_receipts:>10.1f}"
              f" {fa.current_expenditure:>10.1f}"
              f" {fa.depreciation:>8.1f}"
              f" {fa.current_budget_surplus:>10.1f}"
              f" {fa.net_investment:>8.1f}"
              f" {fa.net_borrowing:>10.1f}")


def run_single_vintage(vintage: str):
    print(f"\n{'=' * 60}")
    print(f"  CBP Fiscal Framework — {vintage} vintage")
    print(f"{'=' * 60}")

    dm = load_vintage(vintage)

    # Accounting identity validation
    print()
    print(dm.accounting.summary_report())

    # Model summary
    print_model_summary(dm)

    # Model topology
    print_topology(dm)

    # Economy data summary
    print_economy_summary(dm)

    # Receipts breakdown
    print_receipts_summary(dm)

    # Debt interest
    print_debt_interest_summary(dm)

    # Detailed receipts
    print_detailed_receipts(dm)

    # Fiscal summary table
    print_fiscal_summary(dm, vintage)

    # Equation validation
    print_validation_report(dm)

    # Forward solve
    print_forward_solve(dm)


def run_comparison():
    print(f"\n{'=' * 60}")
    print(f"  CBP Fiscal Framework — Cross-Vintage Comparison")
    print(f"{'=' * 60}")

    managers = {}
    for v in AVAILABLE_VINTAGES:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, '..', 'data', v, 'obr')
        if os.path.isdir(data_dir):
            managers[v] = load_vintage(v)

    # Show PSNB comparison across vintages for overlapping fiscal years
    all_fiscal_years = set()
    vintage_data = {}
    for v, dm in managers.items():
        aggs = dm.get_data('fiscal_aggregates') or []
        vintage_data[v] = {fa.fiscal_year: fa for fa in aggs}
        all_fiscal_years.update(fa.fiscal_year for fa in aggs)

    print(f"\n--- Net Borrowing (PSNB, £bn) across vintages ---\n")
    sorted_fy = sorted(all_fiscal_years)
    header = f"{'Fiscal Year':<14}" + ''.join(f"{v:>14}" for v in managers)
    print(header)
    print('-' * len(header))
    for fy in sorted_fy:
        row = f"{fy:<14}"
        for v in managers:
            fa = vintage_data[v].get(fy)
            row += f"{fa.net_borrowing:>14.1f}" if fa else f"{'':>14}"
        print(row)


def main():
    args = sys.argv[1:]
    use_db = '--db' in args
    args = [a for a in args if a != '--db']
    vintage = args[0] if args else '2026-03'

    if use_db:
        run_from_db(vintage)
    elif vintage == 'all':
        run_comparison()
    elif vintage in AVAILABLE_VINTAGES:
        run_single_vintage(vintage)
    else:
        print(f"Unknown vintage: {vintage}")
        print(f"Available: {', '.join(AVAILABLE_VINTAGES)} or 'all'")
        print(f"Add --db to use the pre-built database (faster, outturn-only state)")
        sys.exit(1)


def run_from_db(vintage: str = '2026-03'):
    """
    Run analysis using the pre-built time series database.

    Faster than run_single_vintage (no XLSX parsing). Loads only OUTTURN
    data into the model state; the forward solver computes the forecast
    period. OBR forecast values are available for comparison in the report.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path  = os.path.join(base_dir, 'db', 'timeseries.db')

    if not os.path.isfile(db_path):
        logger.error("Database not found: %s", db_path)
        logger.error("Build it first:")
        logger.error("  from cbp_fiscal_framework.db.timeseries_db import TimeSeriesDB")
        logger.error("  db = TimeSeriesDB('%s')", db_path)
        logger.error("  db.build_from_obr('data/%s/obr', '%s')", vintage, vintage)
        logger.error("  db.build_from_ons('docs/OBR_Model_Variables_March_2025.xlsx')")
        logger.error("  db.build_ons_mirrors()")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"  CBP Fiscal Framework — {vintage} vintage (DB mode)")
    print(f"{'=' * 60}")

    db = TimeSeriesDB(db_path)
    state, report = build_model_state_from_db(db, obr_pub_date=vintage)
    db.close()

    loaded = report['loaded']
    obr_fc = report['obr_forecast']
    print(f"\n--- Model State (from database) ---")
    print(f"  Variables loaded (outturn): {len(loaded)}")
    print(f"  Date range:                 {report['date_range']}")
    print(f"  OBR forecast reference:     {len(obr_fc)} variables stored for comparison")

    # Load model equations
    model_path = os.path.join(base_dir, '..', 'docs', 'Macroeconomic_model_code_March_2025.txt')
    if not os.path.isfile(model_path):
        logger.error("Model code not found: %s", model_path)
        sys.exit(1)

    from cbp_fiscal_framework.core.winsolve import WinsolveParser, WinsolveModel
    with open(model_path) as f:
        model = WinsolveModel(WinsolveParser.parse_model(f.read()))

    print()
    print(model.summary())

    # Equation validation (runs on outturn period where data exists)
    val_report = validate_equations(model, state)
    print(f"\n--- Equation Validation ---")
    print(f"  Tested: {val_report.tested_equations}  "
          f"Passed: {val_report.passed_equations}  "
          f"Failed: {val_report.failed_equations}  "
          f"Skipped: {val_report.skipped_equations}")
    print(f"  Period checks: {val_report.passed_checks}/{val_report.total_checks}")

    if val_report.per_equation:
        print(f"\n  {'Variable':<12} {'Result':>6} {'Periods':>10} {'Max Resid':>12}  Equation")
        print(f"  {'-'*62}")
        for var in sorted(val_report.per_equation):
            info = val_report.per_equation[var]
            status = 'PASS' if info['passed'] == info['tested'] else 'FAIL'
            print(f"  {var:<12} {status:>6} {info['passed']:>4}/{info['tested']:<4}"
                  f" {info['max_residual']:>12.4f}  {info['raw']}")

    # Forward solve — fills in the forecast period
    print_forward_solve_from_state(model, state, report)

    # Show forecast comparison for key variables
    if obr_fc:
        print(f"\n--- Forecast comparison (CBP solver vs OBR published) ---")
        key_vars = [v for v in ('GDPM', 'CONS', 'LFSUR', 'RHHDI', 'GDPMPS')
                    if v in obr_fc and v in state.values]
        dates = state.dates
        if key_vars:
            header = f"  {'Quarter':<10}" + ''.join(f"{v:>12}" for v in key_vars)
            print(header)
            print(f"  {'-' * (10 + 12*len(key_vars))}")
            for q in ['2026Q1', '2027Q1', '2028Q1', '2029Q1', '2030Q1', '2031Q1']:
                idx = next((i for i, d in enumerate(dates) if d == q), None)
                if idx is None:
                    continue
                row = f"  {q:<10}"
                for v in key_vars:
                    cbp = state.values[v][idx]
                    obr = obr_fc[v].get(q)
                    if cbp is not None and obr is not None:
                        diff = cbp - obr
                        row += f"  {cbp:>6.1f}({diff:+.1f})"
                    elif cbp is not None:
                        row += f"  {cbp:>10.1f}"
                    else:
                        row += f"  {'—':>10}"
                print(row)
            print(f"  (values in £bn CVM or %; parentheses show CBP minus OBR)")


def print_forward_solve_from_state(model, state, mapping_report):
    """Forward solve using an already-built state (DB mode)."""
    from cbp_fiscal_framework.core.winsolve import IdentitySolver, solve_equation

    solver = IdentitySolver(model)
    n_dates = len(state.dates)
    start_t = 1
    solved_vars = set(state.values.keys())
    error_vars = {}

    for t in range(start_t, n_dates):
        state.current_t = t
        for block in solver.blocks:
            try:
                if len(block) == 1:
                    var = block[0]
                    if var not in model._by_name:
                        continue
                    val = solve_equation(model.get_equation(var), state)
                    if val is not None and val == val:
                        if var not in state.values:
                            state.values[var] = [None] * n_dates
                        if state.values[var][t] is None:
                            state.values[var][t] = val
                            solved_vars.add(var)
                else:
                    solver._solve_simultaneous(block, state)
            except Exception as e:
                msg = str(e)
                for var in block:
                    if var not in error_vars:
                        error_vars[var] = (msg, 0)
                    _, count = error_vars[var]
                    error_vars[var] = (msg, count + 1)

    loaded_vars = set(mapping_report['loaded'])
    newly_computed = sorted(solved_vars - loaded_vars)

    print(f"\n--- Forward Solve ---")
    print(f"  Variables solved: {len(solved_vars)} / {solver.identity_count}")
    print(f"  Newly computed (not in loaded state): {len(newly_computed)}")
    if newly_computed:
        shown = ', '.join(newly_computed[:10])
        suffix = f', ... (+{len(newly_computed)-10})' if len(newly_computed) > 10 else ''
        print(f"  Computed: {shown}{suffix}")


if __name__ == '__main__':
    main()
