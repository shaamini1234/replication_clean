# OCR handoff — read the CH accounts PDFs into figures

Give this file + the `ch_pdfs/` folder to the chat/agent doing the OCR.

## What this is
`ch_pdfs/` holds Companies House **accounts PDFs** for FTSE companies (downloaded via
`python/ch_pdf_download.py`). They are almost all **scanned image PDFs** (no text layer) of
full annual reports (200–400 pages). The job: pull the headline financials out of each and
write them to a review CSV — accurately, with evidence, nothing invented.

## Files
- `ch_pdfs/*.pdf` — one file per filing, named `<company_number>_<period_end>.pdf`
  (e.g. `00102498_2024-12-31.pdf`). The company number and the accounts period end are IN
  the filename — that's the join key back to the database.
- `ch_pdfs/manifest.csv` — company_number, company_name, period_end, filing_date, bytes,
  **source_url** (the official CH document URL — keep this as provenance), path.
- `python/ch_pdf_ocr_extract.py` — the extractor to run (already written and tuned to be
  conservative). Reads the folder + manifest, writes `ch_pdfs/ch_ocr_extract_review.csv`.

## How to run
```
pip install pdfplumber pytesseract pdf2image
# system deps: tesseract + poppler   (mac: brew install tesseract poppler)
python3 python/ch_pdf_ocr_extract.py --dir ch_pdfs --limit 5     # pilot first
python3 python/ch_pdf_ocr_extract.py --dir ch_pdfs               # full, resumable
```
It: tries the text layer; if scanned, OCRs each page at LOW dpi only to LOCATE the
consolidated income statement / balance sheet pages, then re-OCRs just those at HIGH dpi to
READ the numbers. This avoids OCR'ing all 400 pages.

## Output columns (`ch_ocr_extract_review.csv`)
`company_number, period_end, metric, value, scale, method, confidence, page, evidence,
sanity_flag, source_url`
- `metric` ∈ revenue, operating_profit, pretax_profit, profit_loss, total_assets,
  net_assets, staff_costs, depreciation.
- `value` is already scaled (£m/£'000 applied from the statement header).
- `method` = text | ocr ; `confidence` = high (text layer) | ocr_review (needs a human glance).
- `evidence` = the exact line the number came from; `page` = where; `source_url` = official CH doc.

## HARD RULES (this project's standard — do not break)
1. **Never invent a number.** If a metric isn't clearly found, leave it blank. A missing
   value is fine; a guessed one is not.
2. **Keep the evidence.** Every value must retain its `evidence` line, `page`, and
   `source_url`. These are what make the figure auditable.
3. **Flag OCR confidence.** OCR'd values are `ocr_review`, not facts, until spot-checked.
   Sanity-flag anything implausible (the script flags total_assets ≪ revenue, etc.).
4. **Units/currency care.** Many FTSE firms report in £m or £'000, some in USD/EUR — the
   scale comes from the statement header; if unclear, flag rather than guess.
5. Coverage reality: this route only reaches ~2011 (CH has nothing machine-readable earlier).
   For 2000–2010 see `LSEG_PULL_SPEC.md` — that's a separate, licensed source.

## After extraction
Spot-check ~15 rows against their `evidence`/`source_url`. Then the figures can be merged
into `business_dynamism_v1_20260820.duckdb` and the consolidated FTSE CSV with
`source='Companies House (OCR, <date>)'` and `confidence` carried through — kept separate
from sourced iXBRL/LSEG facts. Join on `company_number` + the year of `period_end`.
```
```
