# V4 Upgrade — Analytics + 30-minute Tracker

Upload/replace the contents of this package in the ROOT of your existing GitHub repository.

Important files:
- app.py
- index.html
- requirements.txt
- render.yaml
- Procfile
- .python-version
- .github/workflows/mdm-tracker.yml

Then commit to `main`.

## Render
Because V4 adds a Postgres tracker database, open the existing Blueprint in Render and use **Sync Blueprint** after the GitHub commit if the database is not created automatically.

The Blueprint adds:
- existing `assam-mdm-dashboard` web service
- new `assam-mdm-tracker-db` Postgres database
- `DATABASE_URL` wired automatically to the web service

## Start the tracker
After the new deploy is live:
1. Open the dashboard.
2. Open **30m Tracker**.
3. Click **Take Snapshot Now** once.
4. Wait for it to finish. This is the baseline.
5. The next scheduled snapshot creates the first 30-minute comparison.

The included GitHub Actions workflow calls the tracker every 30 minutes.

## Tracker meaning
For each District / Block / Cluster it shows:
- current reporting %
- change in reporting percentage points
- newly reported schools
- reduction in pending schools
- increase in meals served
- Improved / Stable / Regressed indicator

It compares only snapshots from the same source report date, so a new day does not get compared against the previous day's final values.
