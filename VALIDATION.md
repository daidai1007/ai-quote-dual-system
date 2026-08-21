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

Build `2026-08-21-door-variant-v1` validates the five door-count combinations,
selects the matching single/double database product record and applies only the
approved quick-price increments. Formula totals remain unchanged. Regression
coverage also verifies compatibility with the legacy JS/JP quick-only attachment
row so the same transformation cannot be charged twice.

Manual attachment catalogue input is normalized and validated before the API
generates an idempotent PostgreSQL insert. Automated tests do not connect to or
modify Neon.

Nearest-size SQL contracts select the same-product candidate by perimeter
difference first and scale non-standard material, labor, spray, product-area
inputs and quick face price by input perimeter / matched perimeter. BOM totals
remain cabinet-level values and are deliberately not perimeter-scaled.

## v2026.8.18

- API build `2026-08-17-auxiliary-bom-v1` normalizes wide-experience and JM variants before auxiliary-cost lookup while retaining cloud-safe `psql` path configuration.
- The formula quote card exposes an `人工成本折扣系数` control. Changing it immediately recalculates labor cost, the linked 13% management fee, and the formula total from the unmodified database result.
- Draft items persist both the original formula result and the selected labor multiplier, preventing repeated edits from applying the multiplier more than once.
- Client typography and quotation-card sizing were increased for clearer presentation.
