
from flask import Flask, render_template, jsonify, request
import os
import requests
from bs4 import BeautifulSoup
import re

app = Flask(__name__)
BASE = "https://mdmhp.nic.in/Home"
STATE_CODE = "18"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138 Safari/537.36"
})

def get_html(path, params):
    r = session.get(f"{BASE}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.text

def clean_cells(row):
    return [c.get_text(" ", strip=True) for c in row.find_all("td")]

def parse_districts():
    html = get_html("GetDisttWiseSummaryHome", {"stateCode": STATE_CODE})
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select("table tbody tr"):
        cells = clean_cells(tr)
        if len(cells) < 9:
            continue
        clickable = tr.find("td", onclick=True)
        if not clickable:
            continue
        m = re.search(r"GetBlockwiseSummaryDetail\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", clickable.get("onclick",""))
        if not m:
            continue
        out.append({
            "district": cells[1],
            "districtCode": m.group(2),
            "totalSchools": int(cells[2] or 0),
            "monthlyReported": int(cells[3] or 0),
            "monthlyNotReported": int(cells[4] or 0),
            "enrolled": int(cells[5] or 0),
            "dailyReported": int(cells[6] or 0),
            "dailyNotReported": int(cells[7] or 0),
            "mealsServed": int(cells[8] or 0),
        })
    return out

def parse_blocks(district_code):
    html = get_html("GetBlockWiseSummaryHome", {
        "stateCode": STATE_CODE, "districtCode": district_code
    })
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select("table tbody tr"):
        cells = clean_cells(tr)
        if len(cells) < 9:
            continue
        clickable = tr.find("td", onclick=True)
        if not clickable:
            continue
        oc = clickable.get("onclick","")
        codes = re.findall(r"'([^']+)'", oc)
        if len(codes) < 3:
            continue
        out.append({
            "block": cells[1],
            "blockCode": codes[2],
            "totalSchools": int(cells[2] or 0),
            "monthlyReported": int(cells[3] or 0),
            "monthlyNotReported": int(cells[4] or 0),
            "enrolled": int(cells[5] or 0),
            "dailyReported": int(cells[6] or 0),
            "dailyNotReported": int(cells[7] or 0),
            "mealsServed": int(cells[8] or 0),
        })
    return out

def parse_clusters(district_code, block_code):
    html = get_html("GetClusterWiseSummaryHome", {
        "stateCode": STATE_CODE, "districtCode": district_code, "blockCode": block_code
    })
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select("table tbody tr"):
        cells = clean_cells(tr)
        if len(cells) < 9:
            continue
        clickable = tr.find("td", onclick=True)
        if not clickable:
            continue
        codes = re.findall(r"'([^']+)'", clickable.get("onclick",""))
        if len(codes) < 4:
            continue
        out.append({
            "cluster": cells[1],
            "clusterCode": codes[3],
            "totalSchools": int(cells[2] or 0),
            "monthlyReported": int(cells[3] or 0),
            "monthlyNotReported": int(cells[4] or 0),
            "enrolled": int(cells[5] or 0),
            "dailyReported": int(cells[6] or 0),
            "dailyNotReported": int(cells[7] or 0),
            "mealsServed": int(cells[8] or 0),
        })
    return out

def parse_schools(district_code, block_code, cluster_code):
    html = get_html("GetSchoolWiseSummaryHome", {
        "stateCode": STATE_CODE,
        "districtCode": district_code,
        "blockCode": block_code,
        "clusterCode": cluster_code
    })
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select("table tbody tr"):
        cells = clean_cells(tr)
        if len(cells) < 7:
            continue
        span = tr.find("span", onclick=True)
        if not span:
            continue
        codes = re.findall(r"'([^']+)'", span.get("onclick",""))
        if len(codes) < 4:
            continue
        out.append({
            "school": span.get_text(" ", strip=True),
            "schoolCode": codes[1],
            "shift": cells[2],
            "monthlyStatus": cells[3],
            "enrolled": int(cells[4] or 0),
            "dailyStatus": cells[5],
            "mealsServed": int(cells[6] or 0),
        })
    return out

@app.route("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "assam-mdm-dashboard"})

@app.get("/api/districts")
def districts():
    try:
        return jsonify({"ok": True, "data": parse_districts()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/blocks")
def blocks():
    d = request.args.get("districtCode")
    if not d:
        return jsonify({"ok": False, "error": "districtCode required"}), 400
    try:
        return jsonify({"ok": True, "data": parse_blocks(d)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/clusters")
def clusters():
    d = request.args.get("districtCode")
    b = request.args.get("blockCode")
    if not d or not b:
        return jsonify({"ok": False, "error": "districtCode and blockCode required"}), 400
    try:
        return jsonify({"ok": True, "data": parse_clusters(d, b)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/schools")
def schools():
    d = request.args.get("districtCode")
    b = request.args.get("blockCode")
    c = request.args.get("clusterCode")
    if not d or not b or not c:
        return jsonify({"ok": False, "error": "districtCode, blockCode, clusterCode required"}), 400
    try:
        return jsonify({"ok": True, "data": parse_schools(d, b, c)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
