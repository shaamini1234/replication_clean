#!/usr/bin/env python3
"""fetch_ons_geography.py — cache the ONS geography inputs the maps need.

Run once (and again when ONS publishes a new quarterly postcode directory):

    ./venv/bin/python python/fetch_ons_geography.py

It produces three cached files under source_inputs/ons/ (all gitignored — they are
build inputs, not deliverables):

    postcode_lookup.parquet   postcode -> local authority, MSOA, latitude, longitude
    boundaries_lad.geojson    UK local-authority districts, ultra-generalised
    boundaries_msoa.geojson   England & Wales MSOAs, super-generalised
    boundaries_itl3.geojson   UK ITL3 areas (the NUTS3 successor), ultra-generalised
    lad_to_itl3.json          local authority -> ITL3 area
    population_lad.csv        mid-year population estimate per local authority

Boundary coordinates are fetched in WGS84 (EPSG:4326) and projected at build
time. British National Grid was tried first, since ONS publishes in it, but it
covers Great Britain only: Northern Ireland's boundaries come back in Irish Grid
and land on top of Wales. WGS84 is the one request that returns every UK nation
in a single consistent coordinate system.

Sources, all Open Government Licence v3.0 (attribution is rendered on the site):
  - ONS Postcode Directory, Feb 2026 — https://geoportal.statistics.gov.uk/datasets/3080229224424c9cb53c0b48f5a64d27
  - Local Authority Districts (Dec 2025) UK BUC — ONS Open Geography Portal
  - Middle layer Super Output Areas (Dec 2021) EW BSC — ONS Open Geography Portal
  - ITL3 (Jan 2025) UK BUC + the ITL/LAU/LAD lookup — ONS Open Geography Portal
  - Mid-year population estimates by local authority — Nomis (NM_2002_1), ONS.
    Northern Ireland's 11 districts return no value in this dataset, so
    per-capita measures are left unshaded there rather than estimated.

MSOAs cover England and Wales only (6,856 + 408 = 7,264). Scotland uses
Intermediate Zones and Northern Ireland uses Super Output Areas, published by
other agencies; the UK-wide picture therefore uses local authorities.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "source_inputs" / "ons"

ONSPD_ITEM = "3080229224424c9cb53c0b48f5a64d27"          # ONSPD February 2026
ONSPD_ZIP = CACHE / "ONSPD_FEB_2026.zip"
ONSPD_CSV_IN_ZIP = "Data/ONSPD_FEB_2026_UK.csv"
LOOKUP = CACHE / "postcode_lookup.parquet"
LAD_TO_ITL3 = CACHE / "lad_to_itl3.json"
POPULATION = CACHE / "population_lad.csv"
# Population estimates by local authority, latest year, all ages, both sexes.
NOMIS_POP = (
    "https://www.nomisweb.co.uk/api/v01/dataset/NM_2002_1.data.csv"
    "?geography=TYPE432&date=latest&gender=0&c_age=200&measures=20100"
    "&select=geography_code,geography_name,obs_value"
)

ARCGIS = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
BOUNDARIES = {
    "lad": {
        "service": "Local_Authority_Districts_DEC_2025_Boundaries_UK_BUC",
        "fields": "LAD25CD,LAD25NM",
        "out": CACHE / "boundaries_lad.geojson",
    },
    "msoa": {
        "service": "MSOA_2021_EW_BSC_V3_RUC",
        "fields": "MSOA21CD,MSOA21NM",
        "out": CACHE / "boundaries_msoa.geojson",
    },
    "itl3": {
        "service": "ITL3_JAN_2025_UK_BUC_V2",
        "fields": "ITL325CD,ITL325NM",
        "out": CACHE / "boundaries_itl3.geojson",
    },
}
ITL_LOOKUP_SERVICE = "ITL125_ITL225_ITL325_LAU125_LAD25_UK_LU"
PAGE = 1000  # ArcGIS returns at most maxRecordCount features per request


def log(msg: str) -> None:
    print(msg, flush=True)


def download_onspd() -> None:
    if LOOKUP.exists():
        log(f"  ✓ {LOOKUP.name} already cached")
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    if not ONSPD_ZIP.exists():
        url = f"https://www.arcgis.com/sharing/rest/content/items/{ONSPD_ITEM}/data"
        log(f"  downloading ONS Postcode Directory (~235 MB) …")
        with urllib.request.urlopen(url, timeout=1800) as r, open(ONSPD_ZIP, "wb") as f:
            shutil.copyfileobj(r, f)
    csv = CACHE / Path(ONSPD_CSV_IN_ZIP).name
    if not csv.exists():
        log("  extracting the combined UK postcode file (~1.3 GB) …")
        subprocess.run(
            ["unzip", "-o", "-j", str(ONSPD_ZIP), ONSPD_CSV_IN_ZIP, "-d", str(CACHE)],
            check=True, stdout=subprocess.DEVNULL,
        )
    log("  distilling postcode -> local authority + MSOA …")
    con = duckdb.connect()
    con.execute(
        f"""
        copy (
          select upper(replace(pcds, ' ', '')) as pc,
                 nullif(trim(lad25cd), '')  as lad,
                 nullif(trim(msoa21cd), '') as msoa,
                 try_cast(lat as double)    as lat,
                 try_cast(long as double)   as lon
          from read_csv_auto('{csv}', all_varchar=true, sample_size=-1)
          where pcds is not null
        ) to '{LOOKUP}' (format parquet, compression zstd)
        """
    )
    rows = con.execute(
        f"select count(*), count(lad), count(msoa), count(lat) from '{LOOKUP}'"
    ).fetchone()
    log(f"  ✓ {LOOKUP.name}: {rows[0]:,} postcodes "
        f"({rows[1]:,} with LAD, {rows[2]:,} with MSOA, {rows[3]:,} with coordinates)")
    csv.unlink()  # 1.3 GB of raw CSV is not worth keeping; the parquet is the input
    log("  removed the extracted CSV (regenerate from the cached zip if needed)")


def _layer_id(service: str) -> int:
    """Layer ids are per-service on the ONS portal — ITL3 BUC is layer 2, not 0."""
    with urllib.request.urlopen(f"{ARCGIS}/{service}/FeatureServer?f=json", timeout=120) as r:
        layers = json.load(r).get("layers", [])
    return layers[0]["id"] if layers else 0


def fetch_lad_to_itl3() -> None:
    """Local authority to ITL3, the geography that replaced NUTS3 in the UK."""
    if LAD_TO_ITL3.exists():
        log(f"  ✓ {LAD_TO_ITL3.name} already cached")
        return
    base = f"{ARCGIS}/{ITL_LOOKUP_SERVICE}/FeatureServer/{_layer_id(ITL_LOOKUP_SERVICE)}/query"
    mapping, offset = {}, 0
    while True:
        url = (f"{base}?where=1%3D1&outFields=LAD25CD,ITL325CD,ITL325NM&returnGeometry=false"
               f"&f=json&resultOffset={offset}&resultRecordCount={PAGE}")
        with urllib.request.urlopen(url, timeout=300) as r:
            got = json.load(r).get("features", [])
        for f in got:
            a = f["attributes"]
            if a.get("LAD25CD") and a.get("ITL325CD"):
                mapping[a["LAD25CD"]] = {"code": a["ITL325CD"], "name": a["ITL325NM"]}
        if len(got) < PAGE:
            break
        offset += PAGE
    LAD_TO_ITL3.write_text(json.dumps(mapping))
    log(f"  ✓ {LAD_TO_ITL3.name}: {len(mapping):,} local authorities mapped to "
        f"{len({v['code'] for v in mapping.values()}):,} ITL3 areas")


def fetch_population() -> None:
    """Mid-year population estimates per local authority, from Nomis."""
    if POPULATION.exists():
        log(f"  ✓ {POPULATION.name} already cached")
        return
    with urllib.request.urlopen(NOMIS_POP, timeout=300) as r, open(POPULATION, "wb") as f:
        shutil.copyfileobj(r, f)
    lines = POPULATION.read_text().splitlines()
    log(f"  ✓ {POPULATION.name}: {len(lines) - 1:,} local authorities")


def fetch_boundaries(key: str) -> None:
    spec = BOUNDARIES[key]
    out: Path = spec["out"]
    if out.exists():
        log(f"  ✓ {out.name} already cached")
        return
    base = f"{ARCGIS}/{spec['service']}/FeatureServer/{_layer_id(spec['service'])}/query"
    features: list[dict] = []
    offset = 0
    while True:
        url = (
            f"{base}?where=1%3D1&outFields={spec['fields']}&returnGeometry=true"
            f"&outSR=4326&f=geojson&resultOffset={offset}&resultRecordCount={PAGE}"
        )
        with urllib.request.urlopen(url, timeout=300) as r:
            page = json.load(r)
        got = page.get("features", [])
        features.extend(got)
        log(f"    {out.name}: {len(features):,} features")
        if len(got) < PAGE:
            break
        offset += PAGE
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    log(f"  ✓ {out.name}: {len(features):,} features, {out.stat().st_size / 1e6:.1f} MB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="re-fetch even if cached")
    args = ap.parse_args()

    if args.force:
        for p in [LOOKUP, LAD_TO_ITL3, POPULATION, *(b["out"] for b in BOUNDARIES.values())]:
            p.unlink(missing_ok=True)

    log("ONS geography cache")
    download_onspd()
    for key in BOUNDARIES:
        fetch_boundaries(key)
    fetch_lad_to_itl3()
    fetch_population()
    log(f"\nCache ready in {CACHE.relative_to(REPO)} — build the site with:")
    log("  ./venv/bin/python python/build_site_data.py --verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
