# Assam MDM Dashboard V6.1 — Public Previous District Reports

V6.1 fixes the V6 historical-report problem.

## What changed

The old `/Reports/...` historical pages depended on an authenticated browser session, so Render was redirected to the Home page.

V6.1 uses the public Assam date-wise endpoint discovered from the official portal:

- GET `https://mdmhp.nic.in/Home/StateWiseSummary/AS`
- read a fresh `__RequestVerificationToken`
- POST `https://mdmhp.nic.in/Home/DisttWiseSummary`
- form data:
  - `stateCode=18`
  - `mealServedDate=DD/MM/YYYY`
  - fresh anti-forgery token

The returned district table is cached in PostgreSQL.

## Working in V6.1

- Previous District report by selected date
- Total schools / reported / pending / meals served
- 3 / 5 / 7 day official District trend
- 3 / 5 / 7 day poor-performing District analysis immediately
- All-zero non-reporting days (for example Sundays/holidays) are skipped in poor-performance ranking
- Public historical district pages are cached in PostgreSQL
- Existing live District → Block → Cluster → School drill-down remains unchanged
- Existing 30-minute tracker remains unchanged

## Intentionally not guessed

Public historical Block / Cluster / School request endpoints have not yet been captured.
V6.1 therefore does **not** pretend those historical levels work.

Once one public request is captured for:
- Block historical data
- Cluster historical data
- School historical data

they can be added to V6.2 using the same pattern.

## Deploy

Upload/replace all V6.1 files in the existing GitHub repository and commit to `main`.
Render will auto-deploy. The existing PostgreSQL database is reused.
