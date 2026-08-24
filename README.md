# Assam MDM Dashboard V2

This version fixes `TemplateNotFound: index.html`.

The frontend is now a single `index.html` file in the repository root, and Flask serves it directly.
No `templates/` or `static/` folders are required.

Upload these files to the ROOT of your GitHub repository:
- app.py
- index.html
- requirements.txt
- render.yaml
- Procfile

Then commit to `main`. Render should auto-deploy.
