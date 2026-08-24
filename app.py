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
SCHOOL_GAP_LOCK = threading.Lock()


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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS school_gap_runs (
                    id BIGSERIAL PRIMARY KEY,
                    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    report_date TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    incomplete_clusters INTEGER NOT NULL DEFAULT 0,
                    gap_schools INTEGER NOT NULL DEFAULT 0,
                    duration_seconds NUMERIC(10,2) NOT NULL DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS school_daily_failures (
                    id BIGSERIAL PRIMARY KEY,
                    report_date TEXT NOT NULL,
                    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    school_code TEXT NOT NULL,
                    school_name TEXT NOT NULL,
                    shift_id TEXT NOT NULL DEFAULT '1',
                    district_code TEXT,
                    district_name TEXT,
                    block_code TEXT,
                    block_name TEXT,
                    cluster_code TEXT,
                    cluster_name TEXT,
                    monthly_status TEXT,
                    daily_status TEXT,
                    enrolled INTEGER NOT NULL DEFAULT 0,
                    meals_served BIGINT NOT NULL DEFAULT 0,
                    UNIQUE(report_date, school_code, shift_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS ix_school_failures_date ON school_daily_failures(report_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS ix_school_failures_school ON school_daily_failures(school_code)")
            cur.execute("CREATE INDEX IF NOT EXISTS ix_school_gap_runs_date ON school_gap_runs(report_date, captured_at DESC)")
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
            # 7-day analytics only needs a short rolling window. Keep 12 days for safety.
            cur.execute("DELETE FROM tracker_snapshots WHERE to_date(report_date,'DD/MM/YYYY') < CURRENT_DATE - INTERVAL '12 days'")
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


def latest_school_gap_run():
    if not db_enabled():
        return None
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id,captured_at,report_date,source,incomplete_clusters,gap_schools,duration_seconds
                FROM school_gap_runs ORDER BY captured_at DESC LIMIT 1
            """)
            row=cur.fetchone()
    if not row:
        return None
    return {
        "id":row[0],"capturedAt":row[1].isoformat(),"reportDate":row[2],"source":row[3],
        "incompleteClusters":row[4],"gapSchools":row[5],"durationSeconds":float(row[6] or 0)
    }


def school_gap_run(source="manual"):
    """Capture only schools that are still not reported. This is intentionally daily, not every 30 minutes."""
    if not db_enabled():
        raise RuntimeError("Tracker database is not configured.")
    if not SCHOOL_GAP_LOCK.acquire(blocking=False):
        return {"skipped": True, "reason": "A school gap capture is already running."}
    started=datetime.now(timezone.utc)
    try:
        _, live_report_date = parse_districts_with_date()
        latest = latest_snapshot_meta(live_report_date)
        if not latest:
            metrics, live_report_date, duration = collect_tracker_metrics()
            snap_id, captured_at = save_snapshot(metrics, live_report_date, "school-gap-prerequisite", duration)
            latest = {"id": snap_id, "capturedAt": captured_at.isoformat(), "reportDate": live_report_date}

        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT district_code,district_name,block_code,block_name,cluster_code,cluster_name
                    FROM tracker_metrics
                    WHERE snapshot_id=%s AND level='cluster' AND daily_not_reported>0
                    ORDER BY district_name,block_name,cluster_name
                """, (latest["id"],))
                incomplete_clusters=cur.fetchall()

        failures=[]
        fetch_errors=[]
        def fetch_cluster(row):
            dc,dn,bc,bn,cc,cn=row
            rows=parse_schools(dc,bc,cc)
            out=[]
            for school in rows:
                if str(school.get("dailyStatus","")).strip().lower() == "yes":
                    continue
                out.append({
                    "schoolCode":school.get("schoolCode"),"school":school.get("school"),"shift":str(school.get("shift") or "1"),
                    "districtCode":dc,"district":dn,"blockCode":bc,"block":bn,"clusterCode":cc,"cluster":cn,
                    "monthlyStatus":school.get("monthlyStatus"),"dailyStatus":school.get("dailyStatus"),
                    "enrolled":to_int(school.get("enrolled")),"mealsServed":to_int(school.get("mealsServed")),
                })
            return out

        # Low concurrency is deliberate to avoid overloading the source site.
        with ThreadPoolExecutor(max_workers=4) as ex:
            jobs=[ex.submit(fetch_cluster,row) for row in incomplete_clusters]
            for fut in as_completed(jobs):
                try:
                    failures.extend(fut.result())
                except Exception as exc:
                    fetch_errors.append(str(exc))
                    print("School gap cluster warning:", exc, flush=True)

        if fetch_errors:
            raise RuntimeError(f"School gap capture stopped because {len(fetch_errors)} cluster request(s) failed. Existing daily history was left unchanged.")

        duration=(datetime.now(timezone.utc)-started).total_seconds()
        init_db()
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM school_daily_failures WHERE report_date=%s", (live_report_date,))
                cur.execute("""
                    INSERT INTO school_gap_runs(report_date,source,incomplete_clusters,gap_schools,duration_seconds)
                    VALUES(%s,%s,%s,%s,%s) RETURNING id,captured_at
                """, (live_report_date,source,len(incomplete_clusters),len(failures),duration))
                run_id,captured_at=cur.fetchone()
                for f in failures:
                    cur.execute("""
                        INSERT INTO school_daily_failures(
                            report_date,captured_at,school_code,school_name,shift_id,district_code,district_name,
                            block_code,block_name,cluster_code,cluster_name,monthly_status,daily_status,enrolled,meals_served
                        ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(report_date,school_code,shift_id) DO UPDATE SET
                            captured_at=EXCLUDED.captured_at,district_code=EXCLUDED.district_code,district_name=EXCLUDED.district_name,
                            block_code=EXCLUDED.block_code,block_name=EXCLUDED.block_name,cluster_code=EXCLUDED.cluster_code,
                            cluster_name=EXCLUDED.cluster_name,monthly_status=EXCLUDED.monthly_status,daily_status=EXCLUDED.daily_status,
                            enrolled=EXCLUDED.enrolled,meals_served=EXCLUDED.meals_served
                    """, (live_report_date,captured_at,f["schoolCode"],f["school"],f["shift"],f["districtCode"],f["district"],
                          f["blockCode"],f["block"],f["clusterCode"],f["cluster"],f["monthlyStatus"],f["dailyStatus"],f["enrolled"],f["mealsServed"]))
                # Keep a practical rolling history on the small/free database.
                cur.execute("DELETE FROM school_daily_failures WHERE to_date(report_date,'DD/MM/YYYY') < CURRENT_DATE - INTERVAL '35 days'")
                cur.execute("DELETE FROM school_gap_runs WHERE to_date(report_date,'DD/MM/YYYY') < CURRENT_DATE - INTERVAL '35 days'")
            conn.commit()
        return {"skipped":False,"runId":run_id,"capturedAt":captured_at.isoformat(),"reportDate":live_report_date,
                "incompleteClusters":len(incomplete_clusters),"gapSchools":len(failures),"durationSeconds":round(duration,2)}
    finally:
        SCHOOL_GAP_LOCK.release()


def _history_dates_from_tracker(days):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT report_date FROM (
                    SELECT DISTINCT report_date, to_date(report_date,'DD/MM/YYYY') AS report_day
                    FROM tracker_snapshots
                ) d ORDER BY report_day DESC LIMIT %s
            """, (days,))
            return [r[0] for r in cur.fetchall()]


def historical_poor_performers(level="district", days=3, district_code=None, block_code=None, limit=200):
    if not db_enabled():
        raise RuntimeError("Tracker database is not configured.")
    days=max(1,min(int(days),7)); limit=max(1,min(int(limit),500))
    if level == "school":
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT report_date FROM (
                        SELECT DISTINCT report_date, to_date(report_date,'DD/MM/YYYY') AS report_day
                        FROM school_gap_runs
                    ) d ORDER BY report_day DESC LIMIT %s
                """, (days,))
                date_rows=[r[0] for r in cur.fetchall()]
                if not date_rows:
                    return {"level":level,"requestedDays":days,"daysTracked":0,"dates":[],"rows":[]}
                clauses=["report_date = ANY(%s)"]; params=[date_rows]
                if district_code:
                    clauses.append("district_code=%s"); params.append(district_code)
                if block_code:
                    clauses.append("block_code=%s"); params.append(block_code)
                sql=f"""
                    SELECT school_code,MAX(school_name),MAX(shift_id),MAX(district_code),MAX(district_name),
                           MAX(block_code),MAX(block_name),MAX(cluster_code),MAX(cluster_name),
                           COUNT(DISTINCT report_date) AS missed_days,
                           MAX(to_date(report_date,'DD/MM/YYYY')) AS last_gap_date
                    FROM school_daily_failures
                    WHERE {' AND '.join(clauses)}
                    GROUP BY school_code
                    ORDER BY missed_days DESC, last_gap_date DESC, MAX(school_name)
                    LIMIT %s
                """
                params.append(limit)
                cur.execute(sql,params); rows=cur.fetchall()
        total_days=len(date_rows)
        out=[]
        for r in rows:
            missed=int(r[9] or 0); rate=(missed/total_days*100) if total_days else 0
            if missed==total_days and total_days>=2: label="Repeatedly not reported"
            elif missed>=2: label="Needs follow-up"
            else: label="One-day gap"
            out.append({"entityCode":r[0],"entityName":r[1],"shift":r[2],"districtCode":r[3],"districtName":r[4],
                        "blockCode":r[5],"blockName":r[6],"clusterCode":r[7],"clusterName":r[8],
                        "missedDays":missed,"missRate":round(rate,2),"lastGapDate":r[10].strftime('%d/%m/%Y') if r[10] else None,
                        "status":label})
        return {"level":level,"requestedDays":days,"daysTracked":total_days,"dates":date_rows,"rows":out}

    if level not in {"district","block","cluster"}:
        raise ValueError("level must be district, block, cluster or school")
    date_rows=_history_dates_from_tracker(days)
    if not date_rows:
        return {"level":level,"requestedDays":days,"daysTracked":0,"dates":[],"rows":[]}
    clauses=["s.report_date = ANY(%s)","m.level=%s"]; params=[date_rows,level]
    if district_code:
        clauses.append("m.district_code=%s"); params.append(district_code)
    if block_code:
        clauses.append("m.block_code=%s"); params.append(block_code)
    where=' AND '.join(clauses)
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                WITH per_day AS (
                    SELECT DISTINCT ON (s.report_date,m.entity_code)
                        s.report_date,s.captured_at,m.entity_code,m.entity_name,m.district_code,m.district_name,
                        m.block_code,m.block_name,m.cluster_code,m.cluster_name,m.total_schools,m.daily_reported,
                        m.daily_not_reported,m.meals_served,
                        CASE WHEN m.total_schools>0 THEN (m.daily_reported*100.0/m.total_schools) ELSE 0 END AS reporting_pct
                    FROM tracker_metrics m JOIN tracker_snapshots s ON s.id=m.snapshot_id
                    WHERE {where}
                    ORDER BY s.report_date,m.entity_code,s.captured_at DESC
                )
                SELECT entity_code,MAX(entity_name),MAX(district_code),MAX(district_name),MAX(block_code),MAX(block_name),
                       MAX(cluster_code),MAX(cluster_name),COUNT(*) AS tracked_days,
                       SUM(CASE WHEN daily_not_reported>0 THEN 1 ELSE 0 END) AS incomplete_days,
                       AVG(reporting_pct),MIN(reporting_pct),AVG(daily_not_reported),MAX(daily_not_reported),AVG(meals_served)
                FROM per_day
                GROUP BY entity_code
                HAVING SUM(CASE WHEN daily_not_reported>0 THEN 1 ELSE 0 END)>0 OR AVG(reporting_pct)<100
                ORDER BY incomplete_days DESC, AVG(reporting_pct) ASC, AVG(daily_not_reported) DESC
                LIMIT %s
            """, params+[limit])
            rows=cur.fetchall()
    out=[]
    for r in rows:
        tracked=int(r[8] or 0); incomplete=int(r[9] or 0); avg_pct=float(r[10] or 0)
        if tracked and incomplete==tracked and avg_pct<95: label="High attention"
        elif incomplete>=max(2,(tracked+1)//2) or avg_pct<98: label="Needs follow-up"
        else: label="Occasional gap"
        out.append({"entityCode":r[0],"entityName":r[1],"districtCode":r[2],"districtName":r[3],"blockCode":r[4],
                    "blockName":r[5],"clusterCode":r[6],"clusterName":r[7],"daysTracked":tracked,
                    "incompleteDays":incomplete,"avgReportingPct":round(avg_pct,2),"worstReportingPct":round(float(r[11] or 0),2),
                    "avgPending":round(float(r[12] or 0),1),"maxPending":int(r[13] or 0),"avgMeals":round(float(r[14] or 0),1),"status":label})
    return {"level":level,"requestedDays":days,"daysTracked":len(date_rows),"dates":date_rows,"rows":out}


def analytics_insights():
    data=improvements("district")
    rows=data.get("rows",[])
    if not rows:
        return {"latest":data.get("latest"),"previous":data.get("previous"),"items":[]}
    pending=sorted([r for r in rows if r.get("dailyNotReported",0)>0], key=lambda r:r.get("dailyNotReported",0), reverse=True)
    has_previous=bool(data.get("previous"))
    stalled=[r for r in pending if has_previous and r.get("reportedDelta",0)==0]
    improved=sorted(rows,key=lambda r:r.get("reportedDelta",0),reverse=True) if has_previous else []
    meal_up=sorted(rows,key=lambda r:r.get("mealsDelta",0),reverse=True) if has_previous else []
    items=[]
    if pending:
        r=pending[0]; items.append({"kind":"attention","title":"Highest pending","text":f"{r['entityName']} has {r['dailyNotReported']:,} schools still pending."})
    if stalled:
        r=stalled[0]; items.append({"kind":"stalled","title":"No progress in last snapshot","text":f"{r['entityName']} still has {r['dailyNotReported']:,} pending schools and added no new reported schools."})
    if improved and improved[0].get("reportedDelta",0)>0:
        r=improved[0]; items.append({"kind":"good","title":"Fastest reporting improvement","text":f"{r['entityName']} added {r['reportedDelta']:,} reported schools since the previous snapshot."})
    if meal_up and meal_up[0].get("mealsDelta",0)>0:
        r=meal_up[0]; items.append({"kind":"info","title":"Largest meals increase","text":f"{r['entityName']} added {r['mealsDelta']:,} meals since the previous snapshot."})
    return {"latest":data.get("latest"),"previous":data.get("previous"),"items":items}


# -------------------- ROUTES --------------------
@app.route("/")
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "assam-mdm-dashboard-v5", "trackerDb": db_enabled()})


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


@app.get("/api/history/status")
def history_status():
    try:
        latest=latest_school_gap_run() if db_enabled() else None
        tracker_days=len(_history_dates_from_tracker(7)) if db_enabled() else 0
        return jsonify({"ok":True,"configured":db_enabled(),"latestSchoolGap":latest,"trackerDaysAvailable":tracker_days})
    except Exception as e:
        return jsonify({"ok":False,"error":f"{type(e).__name__}: {e}"}),500


@app.post("/api/history/school-gaps/run")
def school_gaps_run_route():
    try:
        source=request.args.get("source","manual")[:30]
        return jsonify({"ok":True,"data":school_gap_run(source)})
    except Exception as e:
        return jsonify({"ok":False,"error":f"{type(e).__name__}: {e}"}),500


@app.get("/api/history/poor")
def history_poor():
    try:
        level=request.args.get("level","district")
        days=to_int(request.args.get("days",3)) or 3
        data=historical_poor_performers(level,days,request.args.get("districtCode"),request.args.get("blockCode"),to_int(request.args.get("limit",200)) or 200)
        return jsonify({"ok":True,"data":data})
    except Exception as e:
        return jsonify({"ok":False,"error":f"{type(e).__name__}: {e}"}),500


@app.get("/api/analytics/insights")
def analytics_insights_route():
    try:
        return jsonify({"ok":True,"data":analytics_insights()})
    except Exception as e:
        return jsonify({"ok":False,"error":f"{type(e).__name__}: {e}"}),500


@app.get("/api/report/poor.csv")
def poor_csv():
    try:
        level=request.args.get("level","district")
        days=to_int(request.args.get("days",7)) or 7
        data=historical_poor_performers(level,days,request.args.get("districtCode"),request.args.get("blockCode"),500)
        buff=io.StringIO(); w=csv.writer(buff)
        if level=="school":
            w.writerow(["Period","School","District","Block","Cluster","Tracked Days","Days Not Reported","Not Reported Rate %","Last Not Reported Date","Follow-up Status"])
            for r in data["rows"]:
                w.writerow([f"Last {data['daysTracked']} tracked days",r["entityName"],r.get("districtName"),r.get("blockName"),r.get("clusterName"),data["daysTracked"],r["missedDays"],r["missRate"],r.get("lastGapDate"),r["status"]])
        else:
            label=level.title()
            w.writerow(["Period",label,"District","Block","Tracked Days","Days With Pending Schools","Average Daily Reporting %","Lowest Daily Reporting %","Average Pending Schools","Highest Pending Schools","Follow-up Status"])
            for r in data["rows"]:
                w.writerow([f"Last {data['daysTracked']} tracked days",r["entityName"],r.get("districtName"),r.get("blockName"),r["daysTracked"],r["incompleteDays"],r["avgReportingPct"],r["worstReportingPct"],r["avgPending"],r["maxPending"],r["status"]])
        filename=f"MDM_Poor_Performance_{level}_{days}days.csv"
        return Response(buff.getvalue(),mimetype="text/csv",headers={"Content-Disposition":f'attachment; filename="{filename}"'})
    except Exception as e:
        return jsonify({"ok":False,"error":f"{type(e).__name__}: {e}"}),500


@app.get("/api/report/daily.csv")
def daily_csv():
    try:
        rows, report_date = parse_districts_with_date()
        buff = io.StringIO()
        w = csv.writer(buff)
        w.writerow(["Report Date","District","Total Schools","Schools Reported Today","Schools Still Pending","Daily Reporting %","Monthly Enrollment Reports Received","Monthly Enrollment Reports Pending","Students in Reported Enrollment","Meals Served Today","Average Meals per Reporting School"])
        for r in rows:
            rp = (r["dailyReported"] / r["totalSchools"] * 100) if r["totalSchools"] else 0
            mps = (r["mealsServed"] / r["dailyReported"]) if r["dailyReported"] else 0
            w.writerow([report_date,r["district"],r["totalSchools"],r["dailyReported"],r["dailyNotReported"],f"{rp:.2f}",r["monthlyReported"],r["monthlyNotReported"],r["enrolled"],r["mealsServed"],f"{mps:.2f}"])
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
