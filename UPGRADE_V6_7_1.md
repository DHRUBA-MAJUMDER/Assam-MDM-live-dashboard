# Assam MDM Dashboard V6.7.1 — Previous Block Parser Fix

## Bug found

The official public historical `POST /Home/BlockWiseSummary` response for
24/08/2026 is a DAILY-only 6-column table:

1. Sr. No.
2. Education Block
3. Total Schools
4. Reported
5. Not Reported
6. No. of Meals Served

V6.7 incorrectly required 9 cells for every Block/Cluster aggregate row.
Therefore valid rows such as:

- BASKA — Total 384, Reported 384, Not Reported 0, Meals 13,358
- JALAH — Total 473, Reported 473, Not Reported 0, Meals 18,143
- TAMULPUR — Total 671, Reported 671, Not Reported 0, Meals 30,235
- TIHU BARAMA — Total 139, Reported 139, Not Reported 0, Meals 5,036

were being rejected, causing the dashboard API to return HTTP 409.

## V6.7.1 fix

Both backend and Chrome extension now accept:

- 6-column daily-only aggregate pages
- 9-column monthly + daily aggregate pages

For a 6-column page, monthly fields and enrollment are stored as `0`
because that response does not provide them; Daily Reported, Daily Not
Reported, and Meals Served are preserved correctly.

Historical School pages still use the Browser Sync extension because they
depend on the authorized browser session.

## Deploy

1. Replace the dashboard repository with V6.7.1.
2. Commit/push to `main` and let Render redeploy.
3. If using Browser Sync, remove/reload the old unpacked extension and load
   the updated `chrome_extension` folder (version 1.0.1).
4. Test `24/08/2026 → BAKSA → blocks`.
5. Then run Browser Sync for BAKSA before opening historical School rows.
