# Assam MDM Dashboard V6.5 — Real Historical District → Block → Cluster → School

V6.5 uses the exact selected-date flow confirmed from DevTools:

1. GET `/Reports/MDM`
2. Read fresh `__RequestVerificationToken`
3. POST `/Reports/MDM/Submit`
   - `CDate=DD/MM/YYYY`
   - fresh verification token
4. Keep the same session cookie
5. GET:
   - `/Reports/BlockReports?stateCode=18&districtCode=...`
   - `/Reports/ClusterReports?stateCode=18&districtCode=...&blockCode=...`
   - `/Reports/SchoolReports?stateCode=18&districtCode=...&blockCode=...&clusterCode=...`

The date is stored in the official server session, which is why directly opening a Reports URL in a fresh Incognito session did not show the selected date.

## What is fixed

- Previous Reports drill-down now works:
  District → Block → Cluster → School
- Reported Excel uses the actual selected historical date.
- Not Reported Excel uses the actual selected historical date.
- Both Excel files include:
  Summary / Districts / Blocks / Clusters / Schools
- School sheet contains:
  District, Block, Cluster, School Name, School Code, Shift, Daily Status, Enrolled, Meals Served
- Excel generation runs in the background with a real progress bar.
- Relevant hierarchy pages are cached in PostgreSQL, so repeat downloads become faster.
- Errors from individual hierarchy pages are written to an `Errors` sheet instead of silently returning an empty workbook.

## Status logic

District / Block / Cluster:
- Reported = at least 1 school reported
- Not Reported = at least 1 school is pending
- A partially reporting area can appear in both workbooks

School:
- Reported = Daily Status Yes
- Not Reported = Daily Status No

## Contact numbers

V6.5 does not bulk-export personal mobile numbers. The historical reporting workbook is limited to school/reporting data.

## Deploy

Replace the existing repo files with V6.5 and commit to `main`.
Render will auto-deploy and reuse the existing PostgreSQL database.
