# Assam MDM Dashboard V6.6 — Public Historical Hierarchy

V6.6 removes the broken `/Reports/...` dependency for previous-date drill-down and Excel.

Confirmed public endpoints:

- District → Block:
  `POST https://mdmhp.nic.in/Home/BlockWiseSummary`
  fields: `stateCode`, `districtCode`, `mealServedDate`, `__RequestVerificationToken`

- Block → Cluster:
  `POST https://mdmhp.nic.in/Home/ClusterWiseSummary`
  fields: `stateCode`, `districtCode`, `blockCode`, `mealServedDate`, `__RequestVerificationToken`

- Cluster → School:
  `POST https://mdmhp.nic.in/Home/SchoolWiseSummary`
  fields: `stateCode`, `districtCode`, `blockCode`, `clusterCode`, `mealServedDate`, `__RequestVerificationToken`

The dashboard first opens:
`https://mdmhp.nic.in/Home/StateWiseSummary/AS`
to get a fresh anti-forgery token and matching cookie, then performs the POST hierarchy above.

## Fixed

- Previous Reports:
  District → Block → Cluster → School
- Reported Excel
- Not Reported Excel
- Historical School Name / School Code / Shift / status
- Selected historical date is sent explicitly as `mealServedDate`
- `/Reports/BlockReports`, `/Reports/ClusterReports`, `/Reports/SchoolReports` are no longer used
- Public hierarchy pages are cached in PostgreSQL
- Excel generation retains the real progress bar and Errors sheet

## Excel logic

District / Block / Cluster:
- Reported = at least one school reported
- Not Reported = at least one school pending

School:
- Reported = Daily Status Yes
- Not Reported = Daily Status No

A partially reporting District/Block/Cluster can correctly appear in both files.

## Head-teacher contact

The official school-user endpoint was identified, but V6.6 does not bulk collect/export personal mobile numbers. This version focuses on historical reporting and school identification data.

## Deploy

Replace the current GitHub repository files with V6.6 and commit to `main`.
Render will reuse the existing PostgreSQL database.
