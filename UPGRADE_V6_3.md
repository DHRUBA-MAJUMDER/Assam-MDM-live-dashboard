# Assam MDM Dashboard V6.3 — Clear School Performance + Progress + Hybrid Previous Data

## Main fixes

### School-level performance is now understandable
Performance Follow-up → Schools shows:
- School Name
- School Code
- Shift
- District / Block / Cluster
- Days Reported
- Days Not Reported
- School Reporting Rate
- Day-by-day green/red status chips
- Follow-up status

Green means the completed daily school-gap capture did not find that school pending.
Red means the school was explicitly found Not Reported on that day.

The table intentionally lists schools that had at least one pending gap in the selected period.

### School CSV is expanded
The downloaded School Follow-up CSV includes a separate date column for every captured day:
- `DD/MM/YYYY Status = Reported`
- `DD/MM/YYYY Status = Not reported`

It also contains School Name, School Code, Shift, District, Block and Cluster.

### Loading / progress bars
- Every dashboard request gets a visible top loading progress bar.
- Manual `Capture Today’s School Status` gets a real progress percentage based on incomplete clusters checked.

### Previous date all-zero fix
If the public previous-date endpoint returns 0 reported / 0 meals for the entire state, V6.3 checks PostgreSQL for that date's latest live tracker snapshot.

If a real tracker snapshot exists:
- it is used as a fallback
- it is labelled `Tracker Final Snapshot`
- a data-quality notice is shown

The dashboard no longer silently tells you that nobody reported when its own tracker has evidence that reporting happened.

## Important limitation
School day-by-day history starts from successful daily school-gap captures. Older school-level days that were never captured cannot be reconstructed without the public historical school endpoint.

## Deploy
Replace the files in the existing GitHub repository with V6.3 and commit to `main`.
Render auto-deploys and reuses the same PostgreSQL database.
