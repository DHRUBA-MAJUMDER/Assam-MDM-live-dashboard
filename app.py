from flask import Flask, jsonify, request, send_from_directory, Response
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import csv
import io
import os
import re
import threading
import requests
from bs4 import BeautifulSoup

try:
    import psycopg
except Exception:
    psycopg = None

app = Flask(__name__)
BASE = "https://mdmhp.nic.in/Home"
STATE_CODE = "18"
DATABASE_URL = os.environ.get("DATABASE_URL", "")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TRACKER_LOCK = threading.Lock()


def get_html(path, params):
    r = requests.get(f"{BASE}/{path}", params=params, headers=HEADERS, timeout=40)
    r.raise_for_status()
    return r.text


def clean_cells(row):
    return [c.get_text(" ", strip=True) for c in row.find_all("td")]


def to_int(value):
    try:
        return int(str(value).replace(",", "").strip() or "0")
    except (ValueError, TypeError):
        return 0


def extract_report_date(html):
    m = re.search(r"Reporting Statistics,\s*(\d{2}/\d{2}/\d{4})", html, re.I)
    return m.group(1) if m else datetime.now().strftime("%d/%m/%Y")


def parse_districts_with_date():
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
        codes = re.findall(r"'([^']+)'", clickable.get("onclick", ""))
        if len(codes) < 2:
            continue
        out.append({
            "district": cells[1],
            "districtCode": codes[1],
            "totalSchools": to_int(cells[2]),
            "monthlyReported": to_int(cells[3]),
            "monthlyNotReported": to_int(cells[4]),
            "enrolled": to_int(cells[5]),
            "dailyReported": to_int(cells[6]),
            "dailyNotReported": to_int(cells[7]),
            "mealsServed": to_int(cells[8]),
        })
    return out, extract_report_date(html)


def parse_districts():
    return parse_districts_with_date()[0]


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
        codes = re.findall(r"'([^']+)'", clickable.get("onclick", ""))
        if len(codes) < 3:
            continue
        out.append({
            "block": cells[1],
            "blockCode": codes[2],
            "totalSchools": to_int(cells[2]),
            "monthlyReported": to_int(cells[3]),
            "monthlyNotReported": to_int(cells[4]),
            "enrolled": to_int(cells[5]),
            "dailyReported": to_int(cells[6]),
            "dailyNotReported": to_int(cells[7]),
            "mealsServed": to_int(cells[8]),
        })
    return out


def parse_clusters(district_code, block_code):
    html = get_html("GetClusterWiseSummaryHome", {
        "stateCode": STATE_CODE,
        "districtCode": district_code,
        "blockCode": block_code,
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
        codes = re.findall(r"'([^']+)'", clickable.get("onclick", ""))
        if len(codes) < 4:
            continue
        out.append({
            "cluster": cells[1],
            "clusterCode": codes[3],
            "totalSchools": to_int(cells[2]),
            "monthlyReported": to_int(cells[3]),
            "monthlyNotReported": to_int(cells[4]),
            "enrolled": to_int(cells[5]),
            "dailyReported": to_int(cells[6]),
            "dailyNotReported": to_int(cells[7]),
            "mealsServed": to_int(cells[8]),
        })
    return out


def parse_schools(district_code, block_code, cluster_code):
    html = get_html("GetSchoolWiseSummaryHome", {
        "stateCode": STATE_CODE,
        "districtCode": district_code,
        "blockCode": block_code,
        "clusterCode": cluster_code,
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
        codes = re.findall(r"'([^']+)'", span.get("onclick", ""))
        if len(codes) < 4:
            continue
        out.append({
            "school": span.get_text(" ", strip=True),
            "schoolCode": codes[1],
            "shift": cells[2],
            "monthlyStatus": cells[3],
            "enrolled": to_int(cells[4]),
            "dailyStatus": cells[5],
            "mealsServed": to_int(cells[6]),
        })
    return out


# -------------------- DATABASE / TRACKER --------------------

def db_enabled():
    return bool(DATABASE_URL and psycopg)


def db_connect():
    if not db_enabled():
        raise RuntimeError("Tracker database is not configured yet.")
    return psycopg.connect(DATABASE_URL)


def init_db():
    if not db_enabled():
        return
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tracker_snapshots (
                    id BIGSERIAL PRIMARY KEY,
                    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    report_date TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    metric_count INTEGER NOT NULL DEFAULT 0,
                    duration_seconds NUMERIC(10,2) NOT NULL DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tracker_metrics (
                    id BIGSERIAL PRIMARY KEY,
                    snapshot_id BIGINT NOT NULL REFERENCES tracker_snapshots(id) ON DELETE CASCADE,
                    level TEXT NOT NULL,
                    entity_code TEXT NOT NULL,
                    entity_name TEXT NOT NULL,
                    district_code TEXT,
                    district_name TEXT,
                    block_code TEXT,
                    block_name TEXT,
                    cluster_code TEXT,
                    cluster_name TEXT,
                    total_schools INTEGER NOT NULL DEFAULT 0,
                    monthly_reported INTEGER NOT NULL DEFAULT 0,
                    monthly_not_reported INTEGER NOT NULL DEFAULT 0,
                    enrolled INTEGER NOT NULL DEFAULT 0,
                    daily_reported INTEGER NOT NULL DEFAULT 0,
                    daily_not_reported INTEGER NOT NULL DEFAULT 0,
                    meals_served BIGINT NOT NULL DEFAULT 0
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS ix_tracker_metrics_snapshot ON tracker_metrics(snapshot_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS ix_tracker_metrics_entity ON tracker_metrics(level, entity_code)")
            cur.execute("CREATE INDEX IF NOT EXISTS ix_tracker_snapshots_date ON tracker_snapshots(report_date, captured_at DESC)")
        conn.commit()


def latest_snapshot_meta(report_date=None):
    if not db_enabled():
        return None
    with db_connect() as conn:
        with conn.cursor() as cur:
            if report_date:
                cur.execute("SELECT id,captured_at,report_date,source,metric_count,duration_seconds FROM tracker_snapshots WHERE report_date=%s ORDER BY captured_at DESC LIMIT 1", (report_date,))
            else:
                cur.execute("SELECT id,captured_at,report_date,source,metric_count,duration_seconds FROM tracker_snapshots ORDER BY captured_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row[0], "capturedAt": row[1].isoformat(), "reportDate": row[2],
                "source": row[3], "metricCount": row[4], "durationSeconds": float(row[5] or 0)
            }


def collect_tracker_metrics():
    started = datetime.now(timezone.utc)
    districts, report_date = parse_districts_with_date()
    metrics = []
    blocks_by_district = {}

    for d in districts:
        metrics.append({
            "level": "district", "entity_code": d["districtCode"], "entity_name": d["district"],
            "district_code": d["districtCode"], "district_name": d["district"],
            "block_code": None, "block_name": None, "cluster_code": None, "cluster_name": None,
            **d,
        })

    # Fetch block summaries in parallel, but keep concurrency deliberately low for the NIC server.
    with ThreadPoolExecutor(max_workers=4) as ex:
        jobs = {ex.submit(parse_blocks, d["districtCode"]): d for d in districts}
        for fut in as_completed(jobs):
            d = jobs[fut]
            try:
                blocks_by_district[d["districtCode"]] = fut.result()
            except Exception:
                blocks_by_district[d["districtCode"]] = []

    cluster_jobs = []
    for d in districts:
        for b in blocks_by_district.get(d["districtCode"], []):
            metrics.append({
                "level": "block", "entity_code": b["blockCode"], "entity_name": b["block"],
                "district_code": d["districtCode"], "district_name": d["district"],
                "block_code": b["blockCode"], "block_name": b["block"],
                "cluster_code": None, "cluster_name": None,
                **b,
            })
            cluster_jobs.append((d, b))

    with ThreadPoolExecutor(max_workers=4) as ex:
        jobs = {ex.submit(parse_clusters, d["districtCode"], b["blockCode"]): (d, b) for d, b in cluster_jobs}
        for fut in as_completed(jobs):
            d, b = jobs[fut]
            try:
                clusters = fut.result()
            except Exception:
                clusters = []
            for c in clusters:
                metrics.append({
                    "level": "cluster", "entity_code": c["clusterCode"], "entity_name": c["cluster"],
                    "district_code": d["districtCode"], "district_name": d["district"],
                    "block_code": b["blockCode"], "block_name": b["block"],
                    "cluster_code": c["clusterCode"], "cluster_name": c["cluster"],
                    **c,
                })

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    return metrics, report_date, duration


def save_snapshot(metrics, report_date, source="manual", duration=0):
    init_db()
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tracker_snapshots(report_date,source,metric_count,duration_seconds) VALUES(%s,%s,%s,%s) RETURNING id,captured_at",
                (report_date, source, len(metrics), duration),
            )
            snapshot_id, captured_at = cur.fetchone()
            values = []
            for m in metrics:
                values.append((
                    snapshot_id, m["level"], m["entity_code"], m["entity_name"],
                    m.get("district_code"), m.get("district_name"), m.get("block_code"), m.get("block_name"),
                    m.get("cluster_code"), m.get("cluster_name"),
                    to_int(m.get("totalSchools")), to_int(m.get("monthlyReported")), to_int(m.get("monthlyNotReported")),
                    to_int(m.get("enrolled")), to_int(m.get("dailyReported")), to_int(m.get("dailyNotReported")),
                    to_int(m.get("mealsServed")),
                ))
            cur.executemany("""
                INSERT INTO tracker_metrics(
                    snapshot_id,level,entity_code,entity_name,district_code,district_name,block_code,block_name,cluster_code,cluster_name,
                    total_schools,monthly_reported,monthly_not_reported,enrolled,daily_reported,daily_not_reported,meals_served
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, values)
        conn.commit()
    return snapshot_id, captured_at


def tracker_run(source="manual", force=False):
    if not db_enabled():
        raise RuntimeError("Tracker database is not configured. Sync the updated render.yaml first.")
    if not TRACKER_LOCK.acquire(blocking=False):
        return {"skipped": True, "reason": "A tracker run is already in progress."}
    try:
        latest = latest_snapshot_meta()
        if latest and not force:
            captured = datetime.fromisoformat(latest["capturedAt"])
            if datetime.now(timezone.utc) - captured < timedelta(minutes=24):
                return {"skipped": True, "reason": "A snapshot was already taken within the last 24 minutes.", "latest": latest}
        metrics, report_date, duration = collect_tracker_metrics()
        snapshot_id, captured_at = save_snapshot(metrics, report_date, source, duration)
        return {
            "skipped": False, "snapshotId": snapshot_id, "capturedAt": captured_at.isoformat(),
            "reportDate": report_date, "metricCount": len(metrics), "durationSeconds": round(duration, 2)
        }
    finally:
        TRACKER_LOCK.release()


def get_snapshot_pair():
    if not db_enabled():
        return None, None
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,captured_at,report_date,source,metric_count,duration_seconds FROM tracker_snapshots ORDER BY captured_at DESC LIMIT 1")
            latest = cur.fetchone()
            if not latest:
                return None, None
            cur.execute("SELECT id,captured_at,report_date,source,metric_count,duration_seconds FROM tracker_snapshots WHERE report_date=%s AND id<>%s ORDER BY captured_at DESC LIMIT 1", (latest[2], latest[0]))
            previous = cur.fetchone()
    def conv(row):
        if not row:
            return None
        return {"id":row[0],"capturedAt":row[1].isoformat(),"reportDate":row[2],"source":row[3],"metricCount":row[4],"durationSeconds":float(row[5] or 0)}
    return conv(latest), conv(previous)


def load_metrics(snapshot_id, level, district_code=None, block_code=None):
    clauses = ["snapshot_id=%s", "level=%s"]
    params = [snapshot_id, level]
    if district_code:
        clauses.append("district_code=%s"); params.append(district_code)
    if block_code:
        clauses.append("block_code=%s"); params.append(block_code)
    sql = f"""SELECT entity_code,entity_name,district_code,district_name,block_code,block_name,cluster_code,cluster_name,
                     total_schools,monthly_reported,monthly_not_reported,enrolled,daily_reported,daily_not_reported,meals_served
              FROM tracker_metrics WHERE {' AND '.join(clauses)}"""
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    keys = ["entityCode","entityName","districtCode","districtName","blockCode","blockName","clusterCode","clusterName",
            "totalSchools","monthlyReported","monthlyNotReported","enrolled","dailyReported","dailyNotReported","mealsServed"]
    return [dict(zip(keys, r)) for r in rows]


def improvements(level="district", district_code=None, block_code=None):
    latest, previous = get_snapshot_pair()
    if not latest:
        return {"latest": None, "previous": None, "rows": []}
    current = load_metrics(latest["id"], level, district_code, block_code)
    prev_map = {}
    if previous:
        prev = load_metrics(previous["id"], level, district_code, block_code)
        prev_map = {r["entityCode"]: r for r in prev}
    rows = []
    for c in current:
        p = prev_map.get(c["entityCode"])
        current_pct = (c["dailyReported"] / c["totalSchools"] * 100) if c["totalSchools"] else 0
        prev_pct = (p["dailyReported"] / p["totalSchools"] * 100) if p and p["totalSchools"] else current_pct
        delta_reported = c["dailyReported"] - (p["dailyReported"] if p else c["dailyReported"])
        pending_reduced = (p["dailyNotReported"] if p else c["dailyNotReported"]) - c["dailyNotReported"]
        meals_delta = c["mealsServed"] - (p["mealsServed"] if p else c["mealsServed"])
        pct_delta = current_pct - prev_pct
        if not p:
            status = "baseline"
        elif delta_reported > 0 or pending_reduced > 0:
            status = "improved"
        elif delta_reported < 0 or pending_reduced < 0:
            status = "regressed"
        else:
            status = "stable"
        row = dict(c)
        row.update({
            "reportingPct": round(current_pct, 2), "reportingPctDelta": round(pct_delta, 2),
            "reportedDelta": delta_reported, "pendingReduced": pending_reduced,
            "mealsDelta": meals_delta, "status": status,
        })
        rows.append(row)
    rows.sort(key=lambda r: (r["status"] != "regressed", r["reportingPct"], -r["dailyNotReported"]))
    return {"latest": latest, "previous": previous, "rows": rows}


def entity_timeline(level, entity_code, limit=16):
    if not db_enabled():
        return []
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.captured_at,s.report_date,m.total_schools,m.daily_reported,m.daily_not_reported,m.meals_served
                FROM tracker_metrics m JOIN tracker_snapshots s ON s.id=m.snapshot_id
                WHERE m.level=%s AND m.entity_code=%s
                ORDER BY s.captured_at DESC LIMIT %s
            """, (level, entity_code, limit))
            rows = cur.fetchall()
    out=[]
    for r in reversed(rows):
        pct = (r[3]/r[2]*100) if r[2] else 0
        out.append({"capturedAt":r[0].isoformat(),"reportDate":r[1],"totalSchools":r[2],"dailyReported":r[3],"dailyNotReported":r[4],"mealsServed":r[5],"reportingPct":round(pct,2)})
    return out


def completion_times():
    if not db_enabled():
        return []
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.entity_code,MAX(m.entity_name),s.report_date,MIN(s.captured_at)
                FROM tracker_metrics m JOIN tracker_snapshots s ON s.id=m.snapshot_id
                WHERE m.level='district' AND m.daily_not_reported=0
                  AND s.report_date=(SELECT report_date FROM tracker_snapshots ORDER BY captured_at DESC LIMIT 1)
                GROUP BY m.entity_code,s.report_date ORDER BY MIN(s.captured_at)
            """)
            rows=cur.fetchall()
    return [{"districtCode":r[0],"district":r[1],"reportDate":r[2],"completedAt":r[3].isoformat()} for r in rows]


# -------------------- ROUTES --------------------
@app.route("/")
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "assam-mdm-dashboard-v4", "trackerDb": db_enabled()})


@app.get("/api/districts")
def districts():
    try:
        rows, report_date = parse_districts_with_date()
        return jsonify({"ok": True, "data": rows, "reportDate": report_date})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/blocks")
def blocks():
    d = request.args.get("districtCode")
    if not d:
        return jsonify({"ok": False, "error": "districtCode required"}), 400
    try:
        return jsonify({"ok": True, "data": parse_blocks(d)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/clusters")
def clusters():
    d = request.args.get("districtCode"); b = request.args.get("blockCode")
    if not d or not b:
        return jsonify({"ok": False, "error": "districtCode and blockCode required"}), 400
    try:
        return jsonify({"ok": True, "data": parse_clusters(d, b)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/schools")
def schools():
    d = request.args.get("districtCode"); b = request.args.get("blockCode"); c = request.args.get("clusterCode")
    if not d or not b or not c:
        return jsonify({"ok": False, "error": "districtCode, blockCode and clusterCode required"}), 400
    try:
        return jsonify({"ok": True, "data": parse_schools(d, b, c)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/tracker/status")
def tracker_status():
    try:
        latest, previous = get_snapshot_pair() if db_enabled() else (None, None)
        return jsonify({"ok": True, "configured": db_enabled(), "latest": latest, "previous": previous})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.post("/api/tracker/run")
def tracker_run_route():
    try:
        force = request.args.get("force") == "1"
        source = request.args.get("source", "manual")[:30]
        return jsonify({"ok": True, "data": tracker_run(source=source, force=force)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/tracker/improvements")
def tracker_improvements():
    level = request.args.get("level", "district")
    if level not in {"district","block","cluster"}:
        return jsonify({"ok": False, "error": "level must be district, block or cluster"}), 400
    try:
        data = improvements(level, request.args.get("districtCode"), request.args.get("blockCode"))
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/tracker/timeline")
def tracker_timeline():
    level = request.args.get("level", "district"); code = request.args.get("code")
    if level not in {"district","block","cluster"} or not code:
        return jsonify({"ok": False, "error": "valid level and code required"}), 400
    try:
        return jsonify({"ok": True, "data": entity_timeline(level, code, min(to_int(request.args.get("limit",16)), 48))})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/tracker/completion")
def tracker_completion():
    try:
        return jsonify({"ok": True, "data": completion_times()})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/report/daily.csv")
def daily_csv():
    try:
        rows, report_date = parse_districts_with_date()
        buff = io.StringIO()
        w = csv.writer(buff)
        w.writerow(["Report Date","District","Total Schools","Daily Reported","Daily Pending","Reporting %","Monthly Reported","Monthly Pending","Enrolled","Meals Served","Meals / Reporting School","Meals as % of Reported Enrollment"])
        for r in rows:
            rp = (r["dailyReported"] / r["totalSchools"] * 100) if r["totalSchools"] else 0
            mps = (r["mealsServed"] / r["dailyReported"]) if r["dailyReported"] else 0
            mer = (r["mealsServed"] / r["enrolled"] * 100) if r["enrolled"] else 0
            w.writerow([report_date,r["district"],r["totalSchools"],r["dailyReported"],r["dailyNotReported"],f"{rp:.2f}",r["monthlyReported"],r["monthlyNotReported"],r["enrolled"],r["mealsServed"],f"{mps:.2f}",f"{mer:.2f}"])
        filename = f"Assam_MDM_{report_date.replace('/','-')}.csv"
        return Response(buff.getvalue(), mimetype="text/csv", headers={"Content-Disposition":f'attachment; filename="{filename}"'})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


try:
    init_db()
except Exception as exc:
    print("Tracker DB init warning:", exc, flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
