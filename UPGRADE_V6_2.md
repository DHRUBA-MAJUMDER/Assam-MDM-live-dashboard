# Assam MDM Dashboard V6.2 — Verified History + Correct CSV Exports

V6.2 fixes two problems reported after V6.1.

## 1. Correct follow-up CSV columns

The CSV is now different for each level:

District:
- District
- District Code
- Days Observed
- performance fields

Block:
- District + District Code
- Block + Block Code
- performance fields

Cluster:
- District + District Code
- Block + Block Code
- Cluster + Cluster Code
- performance fields

School:
- District + District Code
- Block + Block Code
- Cluster + Cluster Code
- School Name
- School Code
- Shift
- Days Observed / Days Not Reported / rate / last gap / status

This removes the duplicate District column and the meaningless blank Block column from district reports.

## 2. Historical trend verification

V6.1 could reuse a stale/incorrect cached district page. V6.2:
- invalidates the old V6.1 public-history cache automatically
- stores a cache-version marker
- matches trend rows using district code AND district name
- falls back to exact district name if the source code/name disagree
- verifies Reported + Pending = Total Schools
- checks for suspicious changes in Total Schools
- compares the historical school total with the current live district reference
- shows a visible Data Check warning if something is suspicious
- adds a `Refresh Official Data` button
- clears old trend rows when a different district is selected

## 3. Sundays / zero-reporting days

The official 3/5/7-day trend now means the last 3/5/7 **active reporting days**.
State-wide all-zero dates are skipped so a Sunday does not turn six 100% days into an 85.71% average.

## Deploy

Upload/replace V6.2 files in the existing GitHub repository and commit to `main`.
Render will auto-deploy and reuse the existing PostgreSQL database.
