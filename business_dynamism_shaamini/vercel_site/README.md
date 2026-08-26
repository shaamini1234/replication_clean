# vercel_site — the public site

A self-contained static site. Every number, percentage, label, axis tick and
tooltip on the page is computed from the canonical DuckDB by
[`python/build_site_data.py`](../python/build_site_data.py) and published in
`data/site.json`. The page itself holds no figures and performs no arithmetic:
it writes the strings the back end produced and hands Chart.js the chart
specifications the back end built.

```
vercel_site/
├── index.html                 markup + prose only — zero numbers
├── app.js                     writes figures in, mounts charts and maps
├── data/site.json             every figure and chart spec (generated)
├── data/map_lad.json          UK local authorities: companies, insolvency share
├── data/map_msoa.json         England & Wales MSOAs: companies, insolvency share
├── data/map_gva.json          value added: total, and per employee
├── vendor/chart.umd.min.js    Chart.js 4.4.1, vendored — no CDN at runtime
├── favicon.svg
├── vercel.json                static config: clean URLs, CSP, cache headers
└── README.md
```

The three map files are fetched lazily — on approach, and in any case shortly
after the charts are up, so a reader who jumps to the end never meets an empty
frame. Choropleth outlines are projected to SVG paths at build time; the page
appends `<path>` elements and draws the legend.

## The two build steps

```bash
./venv/bin/python python/fetch_ons_geography.py      # once, and after each ONS release
./venv/bin/python python/build_site_data.py --verify # after every database change
```

The first caches the ONS postcode directory and boundary files under
`source_inputs/ons/` (gitignored, ~270 MB). The second reads that cache plus the
DuckDB and writes every file under `data/`. Only the second needs re-running day
to day.

## Rebuild the figures after a database change

```bash
cd ..                                              # repo root
./venv/bin/python python/build_site_data.py --verify   # rewrites data/site.json
```

(`duckdb` lives in the repo's `venv`; any interpreter with `duckdb` installed works.)

`--verify` is the wiring gate. It fails if the page references a figure the
build did not produce, if the build produced a figure the page never shows, if a
canvas has no chart spec (or a spec has no canvas), or if any number has been
hardcoded into the prose. It must print `✓` before the site is deployed.

The database is found via `$BD_DUCKDB`, else the first of the paths listed in
`DB_CANDIDATES` at the top of the build script that exists:

```bash
BD_DUCKDB=/path/to/business_dynamism_v2_20260824d.duckdb \
  ./venv/bin/python python/build_site_data.py --verify
```

## Preview locally

```bash
./venv/bin/python -m http.server 8000 --directory vercel_site
open http://localhost:8000
```

Opening `index.html` from the filesystem will not work: the page fetches
`data/site.json`, which a browser blocks over `file://`.

## Deploy

Nothing here needs a build step on Vercel — it is static output plus a JSON
file. Two routes, both using this directory as the project root.

**Vercel CLI**

```bash
npx vercel login                    # once, opens a browser
cd vercel_site
npx vercel                          # preview deployment
npx vercel --prod                   # production deployment
```

**Git integration** — push the repository, then at
[vercel.com/new](https://vercel.com/new) import it and set:

| Setting | Value |
| --- | --- |
| Root Directory | `business_dynamism_shaamini/vercel_site` |
| Framework Preset | Other |
| Build Command | *(leave empty)* |
| Output Directory | *(leave empty)* |

Every later push redeploys. Because the figures live in `data/site.json`, a
refreshed database reaches the site by re-running the build script and
committing the regenerated JSON.

## What the back end decides

Cut-offs and inclusion rules are computed, not written in, so the site stays
correct as the database grows:

- **Partial years.** A year holding less than half the trailing norm is treated
  as incomplete: incorporations stop at the last complete year in the register
  snapshot; the current Gazette year is drawn in grey and labelled partial.
- **Series starts.** The Gazette record's ramp-up year is dropped. Cohort
  survival only shows birth years whose whole five-year window sits inside
  complete Gazette years.
- **Balanced panels.** The FTSE value and dividend panels take the longest
  window that still retains a third of the index unbroken; the base year is the
  year before the sharpest fall, i.e. the pre-crisis peak.
- **Market-cap plausibility.** Some share counts in the source are not
  split-adjusted, which inflates a few constituent market caps by the split
  ratio. Any year in which one constituent exceeds twice the median
  largest-constituent share is excluded from every share-of-total measure, and
  the excluded years are named on the page.
- **Concentration** additionally requires near-complete index coverage, since a
  top-ten share is meaningless with constituents missing.
- **Value added** excludes firm-years whose staff costs or operating profit
  exceed £10bn for a single company-year: the largest legitimate value in the
  panel is about £2bn, and the handful of rows in the hundreds of billions are a
  scale error in the filed-accounts extraction. The count of exclusions is shown
  on the page.
- **Survival curves** are right-censored at the last complete Gazette year and
  stop at the oldest age each whole cohort has been observed to reach. The
  **hazard** curve stops once fewer than a quarter of the population is still
  under observation.
- **Recession bands** mark UK technical recessions (two or more consecutive
  quarters of falling GDP) from the ONS economic-cycle series.

## Geography and licensing

The maps use the ONS Postcode Directory and ONS boundary files, both under the
**Open Government Licence v3.0**; the attribution required by that licence is
rendered beneath every map. Companies are placed at their **registered office**,
which is not necessarily where they trade — formation agents concentrate
thousands of registrations at single addresses, which lifts both the count and
the failure share of the districts they occupy. Middle layer Super Output Areas
are an England and Wales geography, so the MSOA map stops at the Scottish and
Northern Irish borders; the local-authority map covers the whole UK.
