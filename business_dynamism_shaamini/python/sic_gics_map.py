#!/usr/bin/env python3
"""sic_gics_map.py — map a SEC SIC code to the project's GICS sector vocabulary.

Why this exists
---------------
Sector for the S&P universe comes from the live constituent list, so only
CURRENT members have one. Delisted members have no sector but DO retain a SIC
code at SEC EDGAR. To put both on one axis we need SIC -> GICS.

The two schemes do not align cleanly: SIC (1987, US Census) classifies by
PRODUCTION PROCESS; GICS (1999, S&P/MSCI) classifies by REVENUE SOURCE and
end-market. The mapping below is therefore a documented approximation, not an
identity, and every mapped row carries ``sector_basis='edgar_sic_mapped'`` so it
can be told apart from ``sector_basis='index_list_gics'`` downstream.

Resolution order (most specific wins)
-------------------------------------
1. ``COMPANY_OVERRIDE``   — named companies where SIC misleads (see below)
2. ``SIC4``               — exact 4-digit code
3. ``SIC3``               — 3-digit prefix
4. ``SIC2``               — 2-digit major group
5. unmapped -> (None, 'unmapped')

The 2018 GICS reclassification
------------------------------
On 2018-09-21 GICS moved consumer-internet and media companies out of
Information Technology into the new Communication Services sector — Alphabet,
Meta, Twitter, Netflix among them. The live constituent list reflects the CURRENT
rules, so a delisted peer mapped naively from SIC 7370 would land in Information
Technology while its still-listed equivalent sits in Communication Services, and
the sector series would show a spurious shift.

``COMPANY_OVERRIDE`` pins the affected companies to the post-2018 convention so
both halves of the panel follow one rule. This is a methodology choice: it makes
the series internally consistent at the cost of not reproducing the sector label
each company actually carried at the time. Flip ``apply_gics_2018`` to False for
the as-of-the-day reading.

Sources
-------
- SEC, Standard Industrial Classification (SIC) Code List (read 2026-09-15)
  https://www.sec.gov/search-filings/standard-industrial-classification-sic-code-list
- MSCI, "The New GICS Communication Services Sector", September 2018
  https://www.msci.com/documents/10199/bbdd3ff9-b66e-975b-d35d-1028d1013837
"""

from __future__ import annotations

# The 11 GICS sectors — must match source_inputs/ftse100_sector_classification.csv
SECTORS = {
    "Energy", "Materials", "Industrials", "Consumer Discretionary",
    "Consumer Staples", "Health Care", "Financials", "Information Technology",
    "Communication Services", "Utilities", "Real Estate",
}

IT = "Information Technology"
CS = "Communication Services"
CD = "Consumer Discretionary"
CST = "Consumer Staples"
HC = "Health Care"
FIN = "Financials"
IND = "Industrials"
MAT = "Materials"
ENE = "Energy"
UTL = "Utilities"
RE = "Real Estate"

# Companies whose SIC points the wrong way under post-2018 GICS. Keyed on the
# ticker as it appears in the index membership record.
COMPANY_OVERRIDE = {
    # Consumer internet / interactive media — SIC 737x, GICS Communication Services
    "TWTR": CS,    # Twitter — SIC 7370
    "FB": CS,      # Meta Platforms — SIC 7370
    "GOOG": CS, "GOOGL": CS,   # Alphabet — SIC 7370
    "NFLX": CS,    # Netflix — SIC 7841 video rental, GICS Communication Services
    "IAC": CS, "IACI": CS,
    "YHOO": CS,    # Yahoo! pre-Altaba
    # Consumer internet retail — SIC 737x / 5961, GICS Consumer Discretionary
    "AMZN": CD, "EBAY": CD, "EXPE": CD, "BKNG": CD, "PCLN": CD, "TRIP": CD,
    "ETSY": CD, "CHWY": CD, "W": CD,
    # Altaba: post-2017 a closed-end fund holding Alibaba stock, EDGAR SIC blank.
    # Classified Financials on what the entity actually was at exit.
    "AABA": FIN,
}

# Exact 4-digit codes where the major group would mislead.
SIC4 = {
    # --- chemicals 28xx: pharma/biotech are Health Care, the rest Materials ---
    "2833": HC, "2834": HC, "2835": HC, "2836": HC,
    "2840": CST, "2844": CST,     # soap, detergents, cosmetics (P&G, Clorox)
    # --- instruments 38xx: medical devices are Health Care, industrial ones are not ---
    "3812": IND,  # search, detection, navigation, guidance (defence electronics)
    "3823": IND, "3824": IND, "3829": IND,   # industrial measurement & control
    "3825": IT,   # instruments for measuring/testing electricity
    "3826": HC,   # laboratory analytical instruments
    "3827": IT,   # laboratory apparatus / optical
    "3841": HC, "3842": HC, "3843": HC, "3844": HC, "3845": HC, "3851": HC,
    # --- machinery 35xx: computer & office equipment is IT ---
    "3570": IT, "3571": IT, "3572": IT, "3575": IT, "3576": IT, "3577": IT,
    "3578": IT, "3579": IT,
    # --- electrical 36xx: comms equipment + semiconductors are IT ---
    "3600": IND,                     # electrical equipment NEC — industrial by default
    "3612": IND, "3613": IND,        # electrical industrial apparatus
    "3620": IND, "3621": IND,
    "3630": CD, "3634": CD, "3651": CD,   # household appliances / consumer audio
    "3661": IT, "3663": IT, "3669": IT,   # telephone + broadcast equipment
    "3670": IT, "3672": IT, "3674": IT, "3677": IT, "3678": IT, "3679": IT,
    "3690": IND, "3695": IT,
    # --- transport equipment 37xx ---
    "3711": CD, "3713": CD, "3714": CD, "3715": IND, "3716": CD,
    "3721": IND, "3724": IND, "3728": IND, "3730": IND, "3743": IND,
    "3751": CD, "3761": IND, "3790": CD, "3792": CD,
    # --- construction / homebuilders ---
    "1531": CD,                      # operative builders (DR Horton, Lennar, Pulte)
    # --- rubber & plastics ---
    "3021": CD,                      # rubber & plastics footwear (Nike, Deckers)
    # --- retail 5xxx: staples vs discretionary ---
    "5122": HC,                      # wholesale drugs (McKesson, Cardinal, Cencora)
    "5140": CST, "5141": CST, "5149": CST,
    "5331": CST,                     # variety stores (Walmart, Target, Dollar General)
    "5411": CST, "5412": CST, "5912": CST,
    "5960": CD, "5961": CD,
    # --- finance 6xxx: REITs are Real Estate ---
    "4922": ENE, "4953": IND,   # gas transmission / refuse systems (Waste Mgmt)
    "6500": RE, "6510": RE, "6512": RE, "6513": RE, "6519": RE, "6531": RE,
    "6532": RE, "6552": RE, "6798": RE,
    "6324": HC,                 # hospital & medical service plans (managed care)
    "6770": FIN, "6792": ENE,   # blank cheques / oil royalty traders
    # --- services 7xxx ---
    "7310": CS, "7311": CS, "7312": CS, "7319": CS,   # advertising
    "7320": FIN, "7323": FIN,                          # credit reporting / ratings (S&P, Moody's)
    "7330": IND, "7331": IND, "7340": IND, "7350": IND, "7359": IND,
    "7363": IND,                                       # help supply services
    "7372": IT, "7370": IT, "7371": IT, "7373": IT, "7374": IT, "7375": IT,
    "7376": IT, "7377": IT, "7378": IT, "7379": IT,
    "7380": IND, "7381": IND, "7384": CD, "7385": IT, "7389": IND,
    "7812": CS, "7819": CS, "7822": CS, "7829": CS, "7830": CS, "7841": CS,
    "7900": CS, "7990": CS,     # live entertainment / amusement (Live Nation, TKO)
    "7948": CD, "7997": CD,
    "8000": HC, "8011": HC, "8050": HC, "8051": HC, "8060": HC, "8062": HC,
    "8071": HC, "8082": HC, "8090": HC, "8093": HC,
    "8111": IND, "8200": CD, "8300": HC, "8351": CD,
    "8711": IND, "8731": HC, "8734": HC, "8741": IND, "8742": IND, "8744": IND,
    "8880": FIN, "8888": FIN,
}

# 3-digit prefixes.
SIC3 = {
    "131": ENE, "132": ENE, "138": ENE,          # oil & gas extraction / services
    "492": ENE,                                   # natural gas transmission (pipelines)
    "440": CD,                                    # water transportation (cruise lines)
    "495": UTL,                                   # sanitary services

    "291": ENE, "299": ENE,                       # petroleum refining
    "493": UTL, "494": UTL, "495": UTL, "496": UTL, "497": UTL,
    "481": CS, "482": CS, "483": CS, "484": CS, "489": CS,   # communications
    "737": IT,
    "873": HC,
}

# 2-digit major groups — the fallback.
SIC2 = {
    "01": CST, "02": CST, "07": CST, "08": MAT, "09": CST,
    "10": MAT, "12": ENE, "13": ENE, "14": MAT,
    "15": IND, "16": IND, "17": IND,
    "20": CST, "21": CST, "22": CD, "23": CD, "24": IND, "25": CD,
    "26": MAT, "27": CS, "28": MAT, "29": ENE,
    "30": MAT, "31": CD, "32": MAT, "33": MAT, "34": IND, "35": IND,
    "36": IT, "37": IND, "38": HC, "39": CD,
    "40": IND, "41": IND, "42": IND, "44": IND, "45": IND, "46": ENE, "47": IND,
    "48": CS, "49": UTL,
    "50": IND, "51": IND,
    "52": CD, "53": CD, "54": CST, "55": CD, "56": CD, "57": CD, "58": CD, "59": CD,
    "60": FIN, "61": FIN, "62": FIN, "63": FIN, "64": FIN, "65": RE, "67": FIN,
    "70": CD, "72": CD, "73": IT, "75": CD, "76": CD, "78": CS, "79": CD,
    "80": HC, "81": IND, "82": CD, "83": HC, "86": IND, "87": IND, "89": IND,
    "99": None,   # non-classifiable
}


def sic_to_gics(sic: str | int | None, symbol: str | None = None,
                apply_gics_2018: bool = True) -> tuple[str | None, str]:
    """Return ``(sector, basis)``.

    ``basis`` is one of ``company_override``, ``sic4``, ``sic3``, ``sic2``,
    ``unmapped`` — carried into the data so any row can be traced to the rule
    that classified it.
    """
    if apply_gics_2018 and symbol and symbol.upper() in COMPANY_OVERRIDE:
        return COMPANY_OVERRIDE[symbol.upper()], "company_override"

    if sic is None:
        return None, "unmapped"
    s = str(sic).strip()
    if not s or not s.isdigit():
        return None, "unmapped"
    s = s.zfill(4)

    if s in SIC4:
        return SIC4[s], "sic4"
    if s[:3] in SIC3:
        return SIC3[s[:3]], "sic3"
    if s[:2] in SIC2:
        sec = SIC2[s[:2]]
        return (sec, "sic2") if sec else (None, "unmapped")
    return None, "unmapped"


def _self_check() -> int:
    """Assert the table is internally consistent and the known cases land right."""
    bad = [(k, v) for d in (SIC4, SIC3, SIC2) for k, v in d.items()
           if v is not None and v not in SECTORS]
    if bad:
        print(f"FAIL: {len(bad)} entries use a sector outside the GICS vocabulary: {bad[:5]}")
        return 1
    bad = [(k, v) for k, v in COMPANY_OVERRIDE.items() if v not in SECTORS]
    if bad:
        print(f"FAIL: overrides outside vocabulary: {bad}")
        return 1

    cases = [
        ("7372", None, IT, "sic4"),        # PeopleSoft, Siebel, Citrix, Mercury
        ("3674", None, IT, "sic4"),        # Broadcom
        ("3576", None, IT, "sic4"),        # Juniper
        ("7370", "TWTR", CS, "company_override"),
        ("7370", "FB", CS, "company_override"),
        ("7370", "SAPE", IT, "sic4"),      # Sapient — a real IT services firm
        ("2836", None, HC, "sic4"),        # MedImmune
        ("1311", None, ENE, "sic3"),       # Concho Resources
        ("5940", None, CD, "sic2"),        # Staples
        ("4812", None, CS, "sic3"),        # Nextel
        ("4813", None, CS, "sic3"),        # Global Crossing
        ("6798", None, RE, "sic4"),        # REITs
        ("2834", None, HC, "sic4"),        # pharma
        (None, "AABA", FIN, "company_override"),
        ("9995", None, None, "unmapped"),
        ("", None, None, "unmapped"),
    ]
    fails = 0
    for sic, sym, want_sec, want_basis in cases:
        got_sec, got_basis = sic_to_gics(sic, sym)
        if (got_sec, got_basis) != (want_sec, want_basis):
            print(f"FAIL sic={sic!r} sym={sym!r}: got {got_sec!r}/{got_basis} "
                  f"want {want_sec!r}/{want_basis}")
            fails += 1
    print(f"self-check: {len(cases) - fails}/{len(cases)} cases pass; "
          f"{len(SIC4)} sic4 + {len(SIC3)} sic3 + {len(SIC2)} sic2 rules")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_self_check())
