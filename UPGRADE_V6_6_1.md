# Assam MDM Dashboard V6.6.1 — Historical School Parser Fix

The school response format has now been confirmed.

Official historical School-wise rows use this layout:

1. Sr. No.
2. School name with embedded shift, e.g. `1126 NO. ADALBARI SHRIPUR LPS- [Shift ID:1]`
3. Monthly Reported (`Yes/No`)
4. Enrolled
5. Daily Reported (`Yes/No`)
6. Meals Served

V6.6 incorrectly expected a 7-cell school table with a separate Shift column.
That caused every historical school row to be skipped.

V6.6.1 fixes this by:
- accepting the confirmed 6-column layout
- extracting `Shift ID` from the School text
- correctly mapping Monthly Status / Enrolled / Daily Status / Meals Served
- enriching School Code by matching School Name + Shift against the current public school list for the same cluster
- keeping school rows even if School Code matching fails
- bumping the historical cache version so the old bad school cache is not reused

Example confirmed historical row:
- School: `1126 NO. ADALBARI SHRIPUR LPS`
- Shift: `1`
- Monthly Status: `No`
- Enrolled: `0`
- Daily Status: `Yes`
- Meals Served: `12`

Deploy the V6.6.1 files to GitHub `main`; Render will reuse the existing PostgreSQL DB.
