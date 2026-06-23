import logging
from typing import Any, Dict, Optional

from .loaders import OBRForecastLoader, PolicyLoader
from cbp_fiscal_framework.core.accounting import AccountingIdentities

logger = logging.getLogger(__name__)


class DataManager:
    """Central orchestrator for loading and validating OBR data."""

    def __init__(self):
        self.loaders: Dict[str, Any] = {}
        self.data_store: Dict[str, Any] = {}
        self.accounting = AccountingIdentities()

    def register_obr_vintage(self, vintage_dir: str):
        self.loaders['obr'] = OBRForecastLoader(vintage_dir)

    def register_model_code(self, path: str):
        self.loaders['model'] = path

    def register_policy_loader(self, policy_db: str, new_policy_csv: str = None):
        self.loaders['policy'] = PolicyLoader(policy_db, new_policy_csv)

    def load_all_data(self):
        if 'obr' in self.loaders:
            loader = self.loaders['obr']
            self.data_store['fiscal_aggregates'] = loader.load_fiscal_aggregates()
            self.data_store['gdp_components'] = loader.load_gdp_components()
            self.data_store['gdp_income'] = loader.load_gdp_income()
            self.data_store['labour_market'] = loader.load_labour_market()
            self.data_store['market_assumptions'] = loader.load_market_assumptions()
            self.data_store['nominal_gdp'] = loader.load_nominal_gdp_components()
            self.data_store['price_indices'] = loader.load_price_indices()
            self.data_store['household_income'] = loader.load_household_income()
            self.data_store['balance_of_payments'] = loader.load_balance_of_payments()
            self.data_store['household_balance_sheet'] = loader.load_household_balance_sheet()
            self.data_store['receipts_breakdown'] = loader.load_receipts_breakdown()
            self.data_store['detailed_receipts'] = loader.load_detailed_receipts()
            self.data_store['debt_interest'] = loader.load_debt_interest()
            self.data_store['output_gap'] = loader.load_output_gap()
            self.data_store['potential_output'] = loader.load_potential_output()

            aggregates = self.data_store['fiscal_aggregates']
            if aggregates:
                self.accounting.check_all_years(aggregates)

        if 'model' in self.loaders:
            from cbp_fiscal_framework.core.winsolve import WinsolveParser, WinsolveModel
            with open(self.loaders['model']) as f:
                text = f.read()
            equations = WinsolveParser.parse_model(text)
            self.data_store['model'] = WinsolveModel(equations)

        if 'policy' in self.loaders:
            self.data_store['policy_measures'] = self.loaders['policy'].load_measures()

    def get_data(self, key: str) -> Optional[Any]:
        return self.data_store.get(key)
