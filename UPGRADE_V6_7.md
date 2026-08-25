# Assam MDM Dashboard V6.7 — Browser-authenticated Historical Sync

V6.7 solves the historical School problem without copying PM POSHAN cookies to Render.

## Architecture

- Chrome extension runs inside the user's already logged-in `mdmhp.nic.in` tab.
- It obtains the page's normal anti-forgery token.
- It calls:
  - `/Home/DisttWiseSummary`
  - `/Home/BlockWiseSummary`
  - `/Home/ClusterWiseSummary`
  - `/Home/SchoolWiseSummary`
- It parses only reporting/hierarchy rows.
- It uploads those rows to the dashboard using `/api/browser-sync/page`.
- Render stores them in the existing `official_history_cache`.
- Previous Reports and Reported/Not Reported Excel read the archived cache.

No PM POSHAN password, cookie, session token, respondent number, or contact/mobile data is uploaded.

## Required Render setting

Add:
`BROWSER_SYNC_KEY=<long-random-secret>`

The Chrome extension Options page must use the same value.

## Test

First sync:
- Date: `24/08/2026`
- District code: `1824` (BAKSA)

Then open Previous Reports:
BAKSA → BASKA → ADALBARI → School.

## Whole Assam

The extension supports “Sync all Assam”, but this can take a long time because every district/block/cluster/school page must be archived. It deliberately uses small delays instead of hammering the government site.
