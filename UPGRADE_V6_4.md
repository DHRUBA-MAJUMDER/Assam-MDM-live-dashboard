# Assam MDM Dashboard V6.4 — Reported / Not Reported Excel

In **Previous Reports** there are now two buttons:

- Reported Excel
- Not Reported Excel

Each `.xlsx` workbook contains:
- Summary
- Districts
- Blocks
- Clusters
- Schools

Status definition:
- District / Block / Cluster: Reported = 0 pending schools (100% complete)
- District / Block / Cluster: Not Reported = 1+ pending schools
- School: Reported = Daily Status Yes
- School: Not Reported = Daily Status No

Data availability:
- District: previous-date verified source / tracker fallback
- Block + Cluster: final tracker snapshot for that date
- Not Reported School names: daily school-gap capture for that date
- Reported School names: only exact historical school rows that were actually stored

If exact Reported school names were never captured for an older date, the workbook shows an availability note instead of using today's school data.

Deploy by replacing the existing GitHub repo files and committing to `main`.
Render will install the new `XlsxWriter` requirement automatically.
