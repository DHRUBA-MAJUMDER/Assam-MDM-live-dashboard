# Assam MDM Dashboard V6 — Previous Official Reports

V6 adds a real Previous Reports explorer using the official MDM report flow discovered from the portal:

1. GET `/Reports/MDM`
2. Read the fresh `__RequestVerificationToken`
3. POST `/Reports/MDM/Submit` with `CDate`
4. Read:
   - `/Reports/DistrictReports?stateCode=18`
   - `/Reports/BlockReports?stateCode=18&districtCode=...`
   - `/Reports/ClusterReports?stateCode=18&districtCode=...&blockCode=...`
   - `/Reports/SchoolReports?stateCode=18&districtCode=...&blockCode=...&clusterCode=...`

## Important behavior

- The dashboard **does not bypass** the official 5 PM backdated-report restriction.
- Before 5 PM IST, V6 serves only pages already saved in PostgreSQL.
- After 5 PM IST, opening a previous report automatically fetches it from the official source and caches it.
- Once cached, that report page is available from the dashboard at any time.
- A daily workflow archives District → Block → Cluster final pages after 5 PM.
- School pages are automatically archived only for clusters still showing pending schools, to avoid thousands of unnecessary requests to the government server.
- Any school report page you manually open after 5 PM is also cached automatically.

## New UI

Sidebar → **Previous Reports**

- Select a date.
- District → Block → Cluster → School drill-down.
- Source badge shows `Official Source` or `Saved Archive`.
- 3 / 5 / 7 day official trend for the selected District, Block or Cluster.
- Official-trend requests also populate the archive, so the same pages remain available later.

## Deploy

Replace the files in your existing GitHub repository with V6 and commit to `main`.
Render auto-deploys.

The existing PostgreSQL database is reused. V6 creates its new cache tables automatically.

A new workflow is included:
`.github/workflows/mdm-official-final.yml`
