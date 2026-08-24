# V5 Upgrade — Clear Compare + 3–7 Day Poor Performance

Upload/replace the V5 files in the root of the existing GitHub repository and commit to `main`.

## New features
- Plain-language district comparison (no confusing A-minus-B numbers).
- Simple daily report column names.
- 3 / 5 / 7 tracked-day poor-performance analysis for District, Block and Cluster.
- Daily school-gap history for schools that remain not reported.
- Smart analysis cards from the 30-minute tracker.
- 3-day and 7-day follow-up CSV reports.
- Tracker data retention capped to a rolling window to keep the database practical.

## Automation
- `.github/workflows/mdm-tracker.yml`: every 30 minutes from 05:30 AM to 09:00 PM IST.
- `.github/workflows/mdm-school-gaps.yml`: once daily at 07:00 PM IST.

## Important historical-data note
The public endpoint provides the current live state; it does not provide a ready-made 7-day history. Therefore history starts building from the day this tracker is deployed.

District / Block / Cluster history uses the final stored tracker snapshot for each report date.
School history is intentionally lighter: once per day, the system opens only clusters that still have pending schools and stores only the schools that are still not reported. This avoids crawling every school every 30 minutes.

If the daily school capture is run manually earlier in the day and then run again later, the later capture replaces that day's school-gap list.
