# Public release validation

Validated before the initial public-source release:

- Node.js syntax: `api/server.mjs`
- Node.js syntax: `export_dual_quote_workbook.mjs`
- Python syntax: `desktop_client/main.py`
- JSON syntax: public example configuration and request fixtures
- Secret scan: no production password, API key, customer record, local user path, or private drawing/template is included
- Git ignore rules: local configuration, virtual environments, build output, database backups, drawings, spreadsheets, and generated executables are excluded

## Excel exporter limitation

The Excel exporter currently imports `@oai/artifact-tool`. That runtime is not distributed in this repository. The calculation API and desktop client can still be developed without it, but workbook-export regression tests require a compatible implementation of that package or a replacement exporter.

## Data limitation

Migration files define schema and calculation behavior only. Real material prices, attachment prices, formula workbooks, customer history, drawings, and quick-quote experience data must be supplied separately with sanitized test data or local business data.

## Door variant and attachment rules

Run the source regression with:

```powershell
npm test
```

Build `2026-08-21-door-formula-v2` validates all five JS/JP/JA/JE formula
door-count combinations and verifies that the two counts drive formula weight
and area. Other door products accept only 1/0 and 0/1 and select the matching
database single/double record. Quick quote reads SINGLE for all five approved
JS/JP/JA/JE combinations. Door counts still drive attachment quantities and
BOM output, but do not add an automatic surcharge. Formula totals and their
database template selection remain unchanged. Regression coverage also verifies
that the former JS/JP transformation is an ordinary manually selected attachment.

Manual attachment catalogue input is normalized and validated before the API
generates an idempotent PostgreSQL insert. Automated tests do not connect to or
modify Neon.

Nearest-size SQL contracts select the same-product candidate by perimeter
difference first and scale non-standard material, labor, spray, product-area
inputs and quick face price by input perimeter / matched perimeter. BOM totals
remain cabinet-level values and are deliberately not perimeter-scaled.

## v2026.8.18

- API build `2026-08-26-signed-attachments-v1` retains the existing variant normalization and adds signed installation-board selections with positive source-price snapshots.
- The formula quote card exposes an `人工成本折扣系数` control. Changing it immediately recalculates labor cost, the linked 13% management fee, and the formula total from the unmodified database result.
- Draft items persist both the original formula result and the selected labor multiplier, preventing repeated edits from applying the multiplier more than once.
- Client typography and quotation-card sizing were increased for clearer presentation.
