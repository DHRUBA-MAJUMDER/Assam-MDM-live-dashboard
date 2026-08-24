# Assam MDM Live Dashboard

A Flask dashboard for Assam MDM/PM POSHAN reporting data.

## Features

- District live summary
- District → Block → Cluster → School drill-down
- Total schools, daily reporting, pending reporting, meals served
- Search and manual refresh
- Responsive dashboard layout
- Render-ready production configuration
- No school contact/mobile-number harvesting

## Local Run

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:5000`.

## Render

See `DEPLOY_RENDER.md`.
