# Assam MDM Analytics Dashboard V4

## Major features
- Executive dashboard with reporting %, fully reported districts, rankings and Needs Attention.
- District → Block → Cluster → School drill-down.
- Meals Served analysis and contribution percentages.
- 30-minute tracker for **District, Block and Cluster** levels.
- Every tracker snapshot compares with the previous snapshot from the same report date.
- Improvement indicators: reported-school delta, pending reduction, meals increase, reporting-% change, stable/regressed/improved.
- Historical timeline graph for selected tracked entity.
- District completion-time panel once a district reaches zero daily pending.
- Comparison view for two districts.
- CSV daily MIS download.
- Persistent tracker storage with Render Postgres.
- GitHub Actions workflow triggers a snapshot every 30 minutes.

## Deploy / upgrade the existing Render Blueprint
Upload/replace everything in this package to the GitHub repo root, including the `.github/workflows/mdm-tracker.yml` file, then commit to `main`.

Render will sync the Blueprint and add a database named `assam-mdm-tracker-db`. If the database is not automatically added on the first deploy, go to the Render Blueprint page and click **Sync Blueprint**.

After deployment:
1. Open the dashboard.
2. Open **30m Tracker**.
3. Click **Take Snapshot Now** once to create the baseline.
4. GitHub Actions will trigger the next snapshots every 30 minutes.
5. After the second snapshot, improvement deltas become available.

### Important Render free-tier note
Render Free web services can spin down after inactivity, so the included GitHub Actions schedule wakes the service every 30 minutes. Free Render Postgres is suitable for demo/testing but expires after 30 days; use a paid/persistent database for long-term production history.
