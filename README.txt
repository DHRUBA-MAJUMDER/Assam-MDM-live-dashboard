# Chrome Extension Setup

1. In Render, add an environment variable:
   `BROWSER_SYNC_KEY=<a long random secret>`
2. Redeploy V6.7.
3. Chrome → `chrome://extensions`
4. Enable **Developer mode**.
5. Click **Load unpacked** and select this `chrome_extension` folder.
6. Open extension **Options**:
   - Dashboard URL: `https://assam-mdm-dashboard.onrender.com`
   - Browser Sync Key: same value as Render `BROWSER_SYNC_KEY`
7. Log in to PM POSHAN normally in Chrome.
8. Open:
   `https://mdmhp.nic.in/Home/StateWiseSummary/AS`
9. Click the extension, choose historical date and district code.
10. Start with BAKSA (`1824`) to test.
11. Keep the PM POSHAN tab open until the extension says **Sync complete**.
12. Open the dashboard → Previous Reports → same date.

The extension does NOT read or upload your password or cookies. It makes same-site requests inside your already logged-in PM POSHAN tab, parses only reporting tables, and uploads reporting rows to your dashboard.
