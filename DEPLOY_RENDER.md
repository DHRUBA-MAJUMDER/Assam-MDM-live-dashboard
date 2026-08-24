# Assam MDM Dashboard — Render Deployment

This package is ready to deploy as a Render Python Web Service.

## 1) Put the files on GitHub

1. Create a new GitHub repository, for example `assam-mdm-dashboard`.
2. Extract this ZIP on your computer.
3. Upload **all files and folders from inside the extracted folder** to the root of the GitHub repository.
4. Make sure the repository root contains:
   - `app.py`
   - `requirements.txt`
   - `render.yaml`
   - `Procfile`
   - `templates/`
   - `static/`

## 2) Deploy on Render

1. Sign in to Render.
2. Choose **New → Web Service**.
3. Connect your GitHub account and select the repository.
4. Use:
   - Language: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
5. Create the Web Service.

If Render detects `render.yaml`, the included Blueprint already contains the same build/start settings.

## 3) Open the dashboard

After deployment finishes, Render gives you an `onrender.com` URL. Open that URL in any browser or phone. No local CMD window is required.

## Notes

- The dashboard fetches the MDMHP summary endpoints from the server side.
- It loads only the level you open: District → Block → Cluster → School.
- It does not collect school user/contact phone-number data.
- `/healthz` is included for Render health checks.
- For local testing, run `python app.py` and open `http://127.0.0.1:5000`.
