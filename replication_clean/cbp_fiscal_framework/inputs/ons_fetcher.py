"""
ONS API fetcher for OBR model variables.

Reads the OBR_Model_Variables spreadsheet to get ONS series codes,
fetches quarterly data from the ONS API, and applies compound arithmetic
(e.g. ABJR+HAYO, MGRZ-G6NQ-..., 100*(BOKH-ENXO)/(BQKO-BPIX)).

Usage:
    from cbp_fiscal_framework.inputs.ons_fetcher import ONSFetcher
    fetcher = ONSFetcher()
    series = fetcher.fetch('RPQM')          # single code
    series = fetcher.fetch_variable('CONS') # looks up code for CONS and computes
"""

import re
import time
import logging
from typing import Dict, List, Optional, Tuple

import requests
import openpyxl

logger = logging.getLogger(__name__)

ONS_BASE = 'https://www.ons.gov.uk'
RETRY_DELAY = 0.5  # seconds between requests

# ONS code → category path (discovered by probing the ONS website)
ONS_PATHS: Dict[str, str] = {
    # National accounts / GDP
    'EBAQ': '/economy/grossdomesticproductgdp',
    'RPZW': '/economy/grossdomesticproductgdp',
    'NTAO': '/economy/grossdomesticproductgdp',
    'DTWM': '/economy/grossdomesticproductgdp',
    'DTWP': '/economy/grossdomesticproductgdp',
    'ABMM': '/economy/grossdomesticproductgdp',
    'KLS2': '/economy/grossdomesticproductgdp',
    'YBHA': '/economy/grossdomesticproductgdp',
    'ABML': '/economy/grossvalueaddedgva',              # moved from GDP path
    'ABJR': '/economy/grossdomesticproductgdp',
    # Prices
    'GB7S': '/economy/inflationandpriceindices',
    'L55O': '/economy/inflationandpriceindices',
    # Earnings
    'KAC4': '/employmentandlabourmarket/peopleinwork/earningsandworkinghours',
    # Employment
    'MGRZ': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',
    'MGRT': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',
    'MGRW': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',
    # Public sector personnel
    'G6NQ': '/employmentandlabourmarket/peopleinwork/publicsectorpersonnel',
    'G6NT': '/employmentandlabourmarket/peopleinwork/publicsectorpersonnel',
    # Balance of payments / BoP
    'BOKH': '/economy/nationalaccounts/balanceofpayments',
    'ENXO': '/economy/nationalaccounts/balanceofpayments',
    'BPIX': '/economy/nationalaccounts/balanceofpayments',
    'N2V3': '/economy/nationalaccounts/balanceofpayments',
    'BQKO': '/economy/nationalaccounts/balanceofpayments',
    'IKBH': '/economy/nationalaccounts/balanceofpayments',   # XPS
    'IKBI': '/economy/nationalaccounts/balanceofpayments',   # MPS
    'IKBJ': '/economy/nationalaccounts/balanceofpayments',   # TB
    'HBOP': '/economy/nationalaccounts/balanceofpayments',   # CB
    # GDP / national accounts (ONS mirrors of OBR series)
    'ABMI': '/economy/grossdomesticproductgdp',              # GDPM
    'NPQT': '/economy/grossdomesticproductgdp',              # IF
    'ABMG': '/economy/grossdomesticproductgdp',              # TFE
    'ABMF': '/economy/grossdomesticproductgdp',              # TFEPS
    'YBGB': '/economy/grossdomesticproductgdp',              # PGDP
    'NPJR': '/economy/grossdomesticproductgdp',              # VAL
    'NPJQ': '/economy/grossdomesticproductgdp',              # VALPS
    'NPEL': '/economy/grossdomesticproductgdp',              # IBUS
    'CAFU': '/economy/grossdomesticproductgdp',              # DINV
    'CAEX': '/economy/grossdomesticproductgdp',              # DINVPS
    'NMRY': '/economy/grossdomesticproductgdp',              # CGG
    'NMRP': '/economy/grossdomesticproductgdp',              # CGGPS
    # Prices
    'D7BT': '/economy/inflationandpriceindices',             # CPI
    'CHAW': '/economy/inflationandpriceindices',             # PR (RPI)
    'L522': '/economy/inflationandpriceindices',             # CPIH
    'L5P5': '/economy/inflationandpriceindices',             # OOH
    # Employment
    'MGSR': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',   # ER
    'MGWG': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',   # PART16
    'MGRQ': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',   # ESLFS
    # Balance of payments — new codes for missing variables
    'HHCC': '/economy/nationalaccounts/balanceofpayments',   # CGCBOP / CIPD component
    'HBOK': '/economy/nationalaccounts/balanceofpayments',   # CIPD component
    'HBOL': '/economy/nationalaccounts/balanceofpayments',   # DIPD
    'IJAH': '/economy/nationalaccounts/balanceofpayments',   # EECOMPC
    'IJAI': '/economy/nationalaccounts/balanceofpayments',   # EECOMPD
    'IKBN': '/economy/nationalaccounts/balanceofpayments',   # TRANC
    'IKBO': '/economy/nationalaccounts/balanceofpayments',   # TRAND
    'BOXX': '/economy/nationalaccounts/balanceofpayments',   # XOIL / PXOIL component
    'BOKG': '/economy/nationalaccounts/balanceofpayments',   # PXNOG component
    'ELBL': '/economy/nationalaccounts/balanceofpayments',   # PXOIL / PXNOG component
    # GDP / national accounts — new codes (confirmed working paths)
    'NPQS': '/economy/grossdomesticproductgdp',              # PIF component
    'NMES': '/economy/grossdomesticproductgdp',              # CGIPS
    'NMOA': '/economy/governmentpublicsectorandtaxes/publicspending',  # LAIPS
    'L8PS': '/economy/grossdomesticproductgdp',              # EESC component
    'L8Q8': '/economy/grossdomesticproductgdp',              # EESC component
    'L8LU': '/economy/grossdomesticproductgdp',              # EESC component
    'BQKO': '/economy/grossdomesticproductgdp',              # MNOG / PMNOG component
    'BQKQ': '/economy/grossdomesticproductgdp',              # XNOG / PXNOG component
    'IKBF': '/economy/grossdomesticproductgdp',              # MS
    'IKBE': '/economy/grossdomesticproductgdp',              # PXS component
    'IKBB': '/economy/nationalaccounts/balanceofpayments',  # PXS component
    'L635': '/economy/grossdomesticproductgdp',              # PCLEB
    'L637': '/economy/grossdomesticproductgdp',              # IPRL
    'NNRP': '/economy/grossdomesticproductgdp',              # OLPEx component
    'CT9E': '/economy/grossdomesticproductgdp',              # STUDENT / OLPEx component
    'RPZG': '/economy/grossdomesticproductgdp',              # GGIDEF component
    'DLWF': '/economy/grossdomesticproductgdp',              # GGIDEF component
    # UK sector accounts (household balance sheet) — annual series
    'NNMP': '/economy/nationalaccounts/uksectoraccounts',    # DEPHH
    'NNOS': '/economy/nationalaccounts/uksectoraccounts',    # EQHH
    'NPYL': '/economy/nationalaccounts/uksectoraccounts',    # PIHH
    'NNMY': '/economy/nationalaccounts/uksectoraccounts',    # OAHH component
    'NNOA': '/economy/nationalaccounts/uksectoraccounts',    # OAHH component
    'NNPM': '/economy/nationalaccounts/uksectoraccounts',    # OAHH component
    'MMW5': '/economy/nationalaccounts/uksectoraccounts',    # OAHH component
    'NNPP': '/economy/nationalaccounts/uksectoraccounts',    # OLPEx component
    # Prices — RPI components
    'DOBQ': '/economy/inflationandpriceindices',             # PRMIP
    'CHMK': '/economy/inflationandpriceindices',             # PRXMIP
    # --- Auto-discovered paths (Phase 1) ---
    # GDP / national accounts
    'ABMZ': '/economy/grossdomesticproductgdp',
    'ABNG': '/economy/grossdomesticproductgdp',
    'ACAC': '/economy/grossdomesticproductgdp',
    'ACCI': '/economy/grossdomesticproductgdp',
    'ACDD': '/economy/grossdomesticproductgdp',
    'ACDE': '/economy/grossdomesticproductgdp',
    'ACJY': '/economy/grossdomesticproductgdp',
    'AUYN': '/economy/grossdomesticproductgdp',
    'AVAB': '/economy/grossdomesticproductgdp',
    'BKTL': '/economy/grossdomesticproductgdp',
    'C625': '/economy/grossdomesticproductgdp',
    'CAED': '/economy/grossdomesticproductgdp',
    'CAEN': '/economy/grossdomesticproductgdp',
    'CAEQ': '/economy/grossdomesticproductgdp',
    'CAGD': '/economy/grossdomesticproductgdp',
    'CEAN': '/economy/grossdomesticproductgdp',
    'CGBV': '/economy/grossdomesticproductgdp',
    'CGTY': '/economy/grossdomesticproductgdp',
    'CMSU': '/economy/grossdomesticproductgdp',
    'CQOQ': '/economy/grossdomesticproductgdp',
    'CRWF': '/economy/grossdomesticproductgdp',
    'CRWH': '/economy/grossdomesticproductgdp',
    'CUCZ': '/economy/grossdomesticproductgdp',
    'CUEM': '/economy/grossdomesticproductgdp',
    'CUNW': '/economy/grossdomesticproductgdp',
    'D69U': '/economy/grossdomesticproductgdp',
    'DBBO': '/economy/grossdomesticproductgdp',
    'DBJY': '/economy/grossdomesticproductgdp',
    'DMUM': '/economy/grossdomesticproductgdp',
    'DW9E': '/economy/grossdomesticproductgdp',
    'EED5': '/economy/grossdomesticproductgdp',
    'EO2E': '/economy/grossdomesticproductgdp',
    'F8YJ': '/economy/grossdomesticproductgdp',
    'FHLK': '/economy/grossdomesticproductgdp',
    'FKNG': '/economy/grossdomesticproductgdp',
    'FLUK': '/economy/grossdomesticproductgdp',
    'FLVE': '/economy/grossdomesticproductgdp',
    'GAN8': '/economy/grossdomesticproductgdp',
    'GCJG': '/economy/grossdomesticproductgdp',
    'GCMP': '/economy/grossdomesticproductgdp',
    'GCSU': '/economy/grossdomesticproductgdp',
    'GIXM': '/economy/grossdomesticproductgdp',
    'GIXQ': '/economy/grossdomesticproductgdp',
    'GIXS': '/economy/grossdomesticproductgdp',
    'GRXE': '/economy/grossdomesticproductgdp',
    'GTAX': '/economy/grossdomesticproductgdp',
    'I6PB': '/economy/grossdomesticproductgdp',
    'I6PK': '/economy/grossdomesticproductgdp',
    'IE9R': '/economy/grossdomesticproductgdp',
    'IKBK': '/economy/grossdomesticproductgdp',
    'IKBL': '/economy/grossdomesticproductgdp',
    'IV86': '/economy/grossdomesticproductgdp',
    'IV87': '/economy/grossdomesticproductgdp',
    'IV8W': '/economy/grossdomesticproductgdp',
    'J4X2': '/economy/grossdomesticproductgdp',
    'J4X3': '/economy/grossdomesticproductgdp',
    'KW69': '/economy/grossdomesticproductgdp',
    'L62T': '/economy/grossdomesticproductgdp',
    'L62U': '/economy/grossdomesticproductgdp',
    'L634': '/economy/grossdomesticproductgdp',
    'L636': '/economy/grossdomesticproductgdp',
    'L8N8': '/economy/grossdomesticproductgdp',
    'L8R4': '/economy/grossdomesticproductgdp',
    'L8RF': '/economy/grossdomesticproductgdp',
    'LIPG': '/economy/grossdomesticproductgdp',
    'LSNS': '/economy/grossdomesticproductgdp',
    'M9WZ': '/economy/grossdomesticproductgdp',
    'M9X6': '/economy/grossdomesticproductgdp',
    'MA2H': '/economy/grossdomesticproductgdp',
    'MDUP': '/economy/grossdomesticproductgdp',
    'MDYN': '/economy/grossdomesticproductgdp',
    'MIYF': '/economy/grossdomesticproductgdp',
    'NEQA': '/economy/grossdomesticproductgdp',
    'NETE': '/economy/grossdomesticproductgdp',
    'NETR': '/economy/grossdomesticproductgdp',
    'NEVL': '/economy/grossdomesticproductgdp',
    'NFVO': '/economy/grossdomesticproductgdp',
    'NFXV': '/economy/grossdomesticproductgdp',
    'NFYS': '/economy/grossdomesticproductgdp',
    'NG4K': '/economy/grossdomesticproductgdp',
    'NHRB': '/economy/grossdomesticproductgdp',
    'NMEZ': '/economy/grossdomesticproductgdp',
    'NMNL': '/economy/grossdomesticproductgdp',
    'NMRB': '/economy/grossdomesticproductgdp',
    'NRJR': '/economy/grossdomesticproductgdp',
    'NRJS': '/economy/grossdomesticproductgdp',
    'NSSZ': '/economy/grossdomesticproductgdp',
    'NTAR': '/economy/grossdomesticproductgdp',
    'NYOD': '/economy/grossdomesticproductgdp',
    'NYPO': '/economy/grossdomesticproductgdp',
    'NZDV': '/economy/grossdomesticproductgdp',
    'NZDY': '/economy/grossdomesticproductgdp',
    'QWMZ': '/economy/grossdomesticproductgdp',
    'QWPS': '/economy/grossdomesticproductgdp',
    'QWPT': '/economy/grossdomesticproductgdp',
    'QWRY': '/economy/grossdomesticproductgdp',
    'RITQ': '/economy/grossdomesticproductgdp',
    'RNKX': '/economy/grossdomesticproductgdp',
    'ROAW': '/economy/grossdomesticproductgdp',
    'ROAY': '/economy/grossdomesticproductgdp',
    'ROCG': '/economy/grossdomesticproductgdp',
    'ROYL': '/economy/grossdomesticproductgdp',
    'ROYM': '/economy/grossdomesticproductgdp',
    'ROYP': '/economy/grossdomesticproductgdp',
    'ROYT': '/economy/grossdomesticproductgdp',
    'ROYU': '/economy/grossdomesticproductgdp',
    'RPHL': '/economy/grossdomesticproductgdp',
    'RPHQ': '/economy/grossdomesticproductgdp',
    'RPQJ': '/economy/grossdomesticproductgdp',
    'RPQL': '/economy/grossdomesticproductgdp',
    'RPQM': '/economy/grossdomesticproductgdp',
    'RPYN': '/economy/grossdomesticproductgdp',
    'RPYQ': '/economy/grossdomesticproductgdp',
    'RPZT': '/economy/grossdomesticproductgdp',
    'RPZU': '/economy/grossdomesticproductgdp',
    'RPZX': '/economy/grossdomesticproductgdp',
    'RPZY': '/economy/grossdomesticproductgdp',
    'RQBV': '/economy/grossdomesticproductgdp',
    'RQCH': '/economy/grossdomesticproductgdp',
    'RUSD': '/economy/grossdomesticproductgdp',
    'VQSH': '/economy/grossdomesticproductgdp',
    'VQSJ': '/economy/grossdomesticproductgdp',
    'ZAFG': '/economy/grossdomesticproductgdp',
    # Public sector finance
    'AAZK': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ABEC': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ABEI': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ACCJ': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ACUA': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ADAK': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ADDU': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ADSE': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'AIPA': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANBU': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANBX': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANML': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANMW': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANMY': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANNI': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANNN': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANNO': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANNQ': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANNY': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANPZ': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANRV': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANRW': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANRY': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANRZ': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANSO': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANVU': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'BKPX': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'C626': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'CDDZ': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'CPRN': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'CUKY': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'DH7A': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'DHHL': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'EBFE': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'EYOO': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'FCCS': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'GVHE': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'GVHF': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'GZSI': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'GZSJ': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'GZSK': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'GZSO': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'HF6W': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JW2O': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JW2Q': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JW2S': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JW2T': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JW38': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'KIH3': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'KX5Q': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'LSIB': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'MIYZ': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NCBV': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NCXS': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NMCD': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NMCK': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NMFC': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NMFX': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NMYE': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NMYH': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NSRM': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NSRN': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NSRO': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'NUGW': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'RUUW': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    # Public spending
    'CFZG': '/economy/governmentpublicsectorandtaxes/publicspending',
    'E8A6': '/economy/governmentpublicsectorandtaxes/publicspending',
    'EP89': '/economy/governmentpublicsectorandtaxes/publicspending',
    'GTAY': '/economy/governmentpublicsectorandtaxes/publicspending',
    'JT2Q': '/economy/governmentpublicsectorandtaxes/publicspending',
    'L8ND': '/economy/governmentpublicsectorandtaxes/publicspending',
    'LITT': '/economy/governmentpublicsectorandtaxes/publicspending',
    'LIUC': '/economy/governmentpublicsectorandtaxes/publicspending',
    'M9WY': '/economy/governmentpublicsectorandtaxes/publicspending',
    'MDUK': '/economy/governmentpublicsectorandtaxes/publicspending',
    'MDXH': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NIIK': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NMCB': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NMCC': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NMFG': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NMIS': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NMOD': '/economy/governmentpublicsectorandtaxes/publicspending',
    'QYJX': '/economy/governmentpublicsectorandtaxes/publicspending',
    # Balance of payments
    'AA6H': '/economy/nationalaccounts/balanceofpayments',
    'AUSS': '/economy/nationalaccounts/balanceofpayments',
    'BK67': '/economy/nationalaccounts/balanceofpayments',
    'CGDN': '/economy/nationalaccounts/balanceofpayments',
    'FLWB': '/economy/nationalaccounts/balanceofpayments',
    'FLWI': '/economy/nationalaccounts/balanceofpayments',
    'GTTY': '/economy/nationalaccounts/balanceofpayments',
    'H5U3': '/economy/nationalaccounts/balanceofpayments',
    'HBNS': '/economy/nationalaccounts/balanceofpayments',
    'HBQC': '/economy/nationalaccounts/balanceofpayments',
    'HEPX': '/economy/nationalaccounts/balanceofpayments',
    'HEUC': '/economy/nationalaccounts/balanceofpayments',
    'HHZX': '/economy/nationalaccounts/balanceofpayments',
    'HLXV': '/economy/nationalaccounts/balanceofpayments',
    'HLXX': '/economy/nationalaccounts/balanceofpayments',
    'HLXY': '/economy/nationalaccounts/balanceofpayments',
    'HLYD': '/economy/nationalaccounts/balanceofpayments',
    'IKBP': '/economy/nationalaccounts/balanceofpayments',
    'LTEB': '/economy/nationalaccounts/balanceofpayments',
    'N2UG': '/economy/nationalaccounts/balanceofpayments',
    'THAP': '/economy/nationalaccounts/balanceofpayments',
    'XBLW': '/economy/nationalaccounts/balanceofpayments',
    'XBLX': '/economy/nationalaccounts/balanceofpayments',
    'XBMN': '/economy/nationalaccounts/balanceofpayments',
    # UK sector accounts
    'NKWX': '/economy/nationalaccounts/uksectoraccounts',
    'NKZA': '/economy/nationalaccounts/uksectoraccounts',
    'NLBB': '/economy/nationalaccounts/uksectoraccounts',
    'NLBU': '/economy/nationalaccounts/uksectoraccounts',
    'NNML': '/economy/nationalaccounts/uksectoraccounts',
    'NYOT': '/economy/nationalaccounts/uksectoraccounts',
    'NZEA': '/economy/nationalaccounts/uksectoraccounts',
    # Prices / inflation
    'CHOO': '/economy/inflationandpriceindices',
    'CZXD': '/economy/inflationandpriceindices',
    'CZXE': '/economy/inflationandpriceindices',
    'D7CE': '/economy/inflationandpriceindices',
    'DOBR': '/economy/inflationandpriceindices',
    'KYHJ': '/economy/inflationandpriceindices',
    'KYHL': '/economy/inflationandpriceindices',
    'KYHM': '/economy/inflationandpriceindices',
    'L5PA': '/economy/inflationandpriceindices',
    # Employment
    'DYDC': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',
    'DYZN': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',
    'LOJU': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',
    'MGSL': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',
    'YBUS': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',
    'YBUV': '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes',
    # Public sector personnel
    'G6NW': '/employmentandlabourmarket/peopleinwork/publicsectorpersonnel',
    # --- Auto-discovered paths (Phase 5 batch) ---
    # Public spending
    'ACCH': '/economy/governmentpublicsectorandtaxes/publicspending',
    'LSON': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NSFA': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NRQB': '/economy/governmentpublicsectorandtaxes/publicspending',
    'IY9O': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NSEZ': '/economy/governmentpublicsectorandtaxes/publicspending',
    'CUDB': '/economy/governmentpublicsectorandtaxes/publicspending',
    'LITK': '/economy/governmentpublicsectorandtaxes/publicspending',
    'L8UA': '/economy/governmentpublicsectorandtaxes/publicspending',
    'CT9U': '/economy/governmentpublicsectorandtaxes/publicspending',
    'CRSN': '/economy/governmentpublicsectorandtaxes/publicspending',
    'FJWE': '/economy/governmentpublicsectorandtaxes/publicspending',
    'FJWG': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NPVQ': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NIJI': '/economy/governmentpublicsectorandtaxes/publicspending',
    'NPUP': '/economy/governmentpublicsectorandtaxes/publicspending',
    # Public sector finance
    'BKSM': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'BKSN': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'BKSO': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'BKQG': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'QYJR': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANND': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANVQ': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JXJ4': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'GVHG': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JW29': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANCW': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANRH': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ANRS': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'ABIF': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    # GDP / national accounts
    'CQTC': '/economy/grossdomesticproductgdp',
    'NZFS': '/economy/grossdomesticproductgdp',
    'NZFV': '/economy/grossdomesticproductgdp',
    'LITR': '/economy/grossdomesticproductgdp',
    'DFT5': '/economy/grossdomesticproductgdp',
    'ACDF': '/economy/grossdomesticproductgdp',
    'ACDG': '/economy/grossdomesticproductgdp',
    'ACDH': '/economy/grossdomesticproductgdp',
    'ACDI': '/economy/grossdomesticproductgdp',
    'CYNX': '/economy/grossdomesticproductgdp',
    'RUTC': '/economy/grossdomesticproductgdp',
    'DKHE': '/economy/grossdomesticproductgdp',
    'DBKE': '/economy/grossdomesticproductgdp',
    'KIY5': '/economy/grossdomesticproductgdp',
    'DKHH': '/economy/grossdomesticproductgdp',
    'ZYBE': '/economy/grossdomesticproductgdp',
    'IV8F': '/economy/grossdomesticproductgdp',
    'IV8E': '/economy/grossdomesticproductgdp',
    'QWRZ': '/economy/grossdomesticproductgdp',
    'NMKK': '/economy/grossdomesticproductgdp',
    'F8YF': '/economy/grossdomesticproductgdp',
    'F8YH': '/economy/grossdomesticproductgdp',
    'NETZ': '/economy/grossdomesticproductgdp',
    'NMGR': '/economy/grossdomesticproductgdp',
    'NMGT': '/economy/grossdomesticproductgdp',
    'MDYL': '/economy/grossdomesticproductgdp',
    'CFGW': '/economy/grossdomesticproductgdp',
    'GCSW': '/economy/grossdomesticproductgdp',
    'GCMR': '/economy/grossdomesticproductgdp',
    'NMQZ': '/economy/grossdomesticproductgdp',
    'FKNN': '/economy/grossdomesticproductgdp',
    'FLVY': '/economy/grossdomesticproductgdp',
    'NMAI': '/economy/grossdomesticproductgdp',
    'NMJF': '/economy/grossdomesticproductgdp',
    # Balance of payments
    'FJUO': '/economy/nationalaccounts/balanceofpayments',
    'FJCK': '/economy/nationalaccounts/balanceofpayments',
    'MUV5': '/economy/nationalaccounts/balanceofpayments',
    'MUV6': '/economy/nationalaccounts/balanceofpayments',
    'FKKM': '/economy/nationalaccounts/balanceofpayments',
    'FHJL': '/economy/nationalaccounts/balanceofpayments',
    'FLWT': '/economy/nationalaccounts/balanceofpayments',
    # UK sector accounts
    'NKIF': '/economy/nationalaccounts/uksectoraccounts',
    'NKFB': '/economy/nationalaccounts/uksectoraccounts',
    # Public sector personnel
    'C9K9': '/employmentandlabourmarket/peopleinwork/publicsectorpersonnel',
    'C9KA': '/employmentandlabourmarket/peopleinwork/publicsectorpersonnel',
}


class ONSFetcher:
    def __init__(self, variables_xlsx: str = None):
        self._cache: Dict[str, Dict[str, float]] = {}  # code -> {YYYYQN: value}
        self._var_map: Dict[str, str] = {}             # model_var -> ons_formula
        if variables_xlsx:
            self._load_var_map(variables_xlsx)

    # ── spreadsheet loader ────────────────────────────────────────────────────

    def _load_var_map(self, path: str):
        wb = openpyxl.load_workbook(path, read_only=True)
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            if not row or not row[2]:
                continue
            model_var = str(row[2]).strip()
            ons_code = str(row[3]).strip() if row[3] else ''
            if ons_code in ('No Codes', 'Codes', '', 'ONS identifier code'):
                continue
            self._var_map[model_var] = ons_code
        wb.close()
        logger.info("Loaded %d variable→ONS code mappings", len(self._var_map))

    # ── ONS API ───────────────────────────────────────────────────────────────

    def fetch(self, code: str) -> Dict[str, float]:
        """Fetch a single ONS series. Returns {YYYYQN: value} dict."""
        code = code.strip()
        if code in self._cache:
            return self._cache[code]

        path = ONS_PATHS.get(code)
        if not path:
            logger.warning("No path known for ONS code %s — skipping", code)
            return {}

        url = f'{ONS_BASE}{path}/timeseries/{code}/data'
        try:
            resp = requests.get(url, timeout=15,
                                headers={'User-Agent': 'Mozilla/5.0',
                                         'Accept': 'application/json'})
            resp.raise_for_status()
            data = resp.json()
        except requests.HTTPError as e:
            logger.warning("ONS error for %s: %s", code, e)
            self._cache[code] = {}  # cache failure so we don't hammer the API
            return {}
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", code, e)
            self._cache[code] = {}  # cache failure so we don't hammer the API
            return {}

        result = {}
        for item in data.get('quarters', []):
            try:
                year = item['year']
                qtr  = item['quarter']  # 'Q1', 'Q2', 'Q3', 'Q4'
                val  = float(item['value'].replace(',', ''))
                result[f"{year}{qtr}"] = val
            except (KeyError, ValueError):
                pass

        # Fall back to annual data when no quarterly series exists (e.g. household balance sheet stocks).
        # Spread each annual value across all four quarters of that year.
        if not result:
            for item in data.get('years', []):
                try:
                    year = item['year']
                    val  = float(item['value'].replace(',', ''))
                    for q in ('Q1', 'Q2', 'Q3', 'Q4'):
                        result[f"{year}{q}"] = val
                except (KeyError, ValueError):
                    pass

        time.sleep(RETRY_DELAY)
        self._cache[code] = result
        logger.info("Fetched %s: %d quarterly observations", code, len(result))
        return result

    # ── formula parser ────────────────────────────────────────────────────────

    def _extract_codes(self, formula: str) -> List[str]:
        """Extract raw ONS series codes from a formula string."""
        # Strip formula functions like 100*(...) and isolate bare codes
        # ONS codes: letters + digits, 4-6 chars
        tokens = re.findall(r'[A-Z][A-Z0-9]{2,6}', formula)
        # Filter out numeric-only patterns that slipped through
        return [t for t in tokens if not t.isdigit()]

    def compute_formula(self, formula: str, date_key: str) -> Optional[float]:
        """
        Evaluate a compound ONS formula for a specific quarter.

        Handles:
          - Simple code: RPQM
          - Sum/diff: ABJR+HAYO, MGRZ-G6NQ-G6NT
          - Ratio formula: 100*(BOKH-ENXO)/(BQKO-BPIX)
          - Ratio: NETZ/NLBU
        """
        formula = formula.strip()

        # Fetch all codes referenced in the formula
        codes = self._extract_codes(formula)
        vals: Dict[str, float] = {}
        for code in codes:
            series = self.fetch(code)
            v = series.get(date_key)
            if v is None:
                return None
            vals[code] = v

        # Build a safe expression by substituting code→value
        expr = formula
        # Sort by length desc to avoid partial substitutions
        for code in sorted(vals, key=len, reverse=True):
            expr = expr.replace(code, str(vals[code]))

        try:
            return float(eval(expr))  # noqa: S307
        except Exception:
            return None

    # ── public interface ──────────────────────────────────────────────────────

    def fetch_variable(self, model_var: str) -> Dict[str, float]:
        """
        Fetch and compute a model variable using its ONS formula.
        Returns {YYYYQN: value} dict.
        """
        formula = self._var_map.get(model_var)
        if not formula:
            logger.warning("No ONS code for model variable %s", model_var)
            return {}

        # Get all unique dates from component series
        codes = self._extract_codes(formula)
        all_dates: set = set()
        for code in codes:
            all_dates |= set(self.fetch(code).keys())

        result = {}
        for date_key in sorted(all_dates):
            v = self.compute_formula(formula, date_key)
            if v is not None:
                result[date_key] = v

        return result

    def fetch_variables(self, model_vars: List[str]) -> Dict[str, Dict[str, float]]:
        """Fetch multiple model variables. Returns {model_var: {YYYYQN: value}}."""
        return {var: self.fetch_variable(var) for var in model_vars}

    def available_variables(self) -> List[Tuple[str, str]]:
        """Return list of (model_var, ons_formula) pairs."""
        return list(self._var_map.items())

    def to_quarterly_series(self,
                            data: Dict[str, float],
                            dates: List[str]) -> List[Optional[float]]:
        """Align a {YYYYQN: value} dict to a canonical date list."""
        return [data.get(d) for d in dates]