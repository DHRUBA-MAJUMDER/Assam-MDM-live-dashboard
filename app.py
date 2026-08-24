from flask import Flask, jsonify, request, send_from_directory, Response
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import csv
import io
import os
import re
import threading
import json
from urllib.parse import urlparse, parse_qs
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
OFFICIAL_ARCHIVE_LOCK = threading.Lock()
REPORTS_BASE = "https://mdmhp.nic.in/Reports"
IST = timezone(timedelta(hours=5, minutes=30))


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




# -------------------- PUBLIC HISTORICAL DISTRICT REPORTS --------------------

PUBLIC_STATE_REPORT_URL = "https://mdmhp.nic.in/Home/StateWiseSummary/AS"
PUBLIC_DISTRICT_HISTORY_URL = "https://mdmhp.nic.in/Home/DisttWiseSummary"
PUBLIC_HISTORY_CACHE_VERSION = "v6.2-public-district-verified"


def normalize_district_name(value):
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def parse_public_historical_districts(html):
    """Parse the public date-wise district table.
    Layout: Sr.No, District, Total Schools, Reported, Not Reported, Meals Served.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tbody tr"):
        cells = clean_cells(tr)
        if len(cells) < 6:
            continue
        district_cell = tr.find("td", onclick=True)
        if not district_cell:
            continue
        codes = re.findall(r"'([^']+)'", district_cell.get("onclick", ""))
        district_code = codes[1] if len(codes) >= 2 else None
        district_name = cells[1].strip()
        if not district_code or not district_name:
            continue
        rows.append({
            "district": district_name,
            "districtCode": district_code,
            "totalSchools": to_int(cells[2]),
            "monthlyReported": 0,
            "monthlyNotReported": 0,
            "enrolled": 0,
            "dailyReported": to_int(cells[3]),
            "dailyNotReported": to_int(cells[4]),
            "mealsServed": to_int(cells[5]),
        })
    return rows


def fetch_public_district_history(report_date, refresh=False):
    """Use the public StateWiseSummary form and its fresh anti-forgery token.
    V6.2 only trusts cache written by the verified parser version.
    """
    report_date = validate_report_date(report_date)

    if not refresh:
        cached = load_official_cache(report_date, "district")
        if cached and cached.get("cacheVersion") == PUBLIC_HISTORY_CACHE_VERSION:
            cached["source"] = "archive"
            return cached

    # Remove stale/legacy cache for this date before writing the verified copy.
    if db_enabled():
        try:
            scope_key = history_scope_key("district")
            with db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM official_history_cache "
                        "WHERE report_date=%s AND level='district' AND scope_key=%s",
                        (report_date, scope_key),
                    )
                conn.commit()
        except Exception as exc:
            print("Historical cache cleanup warning:", exc, flush=True)

    s = requests.Session()
    s.headers.update(HEADERS)

    landing = s.get(PUBLIC_STATE_REPORT_URL, timeout=40)
    landing.raise_for_status()
    soup = BeautifulSoup(landing.text, "html.parser")
    token = soup.find("input", attrs={"name": "__RequestVerificationToken"})
    if not token or not token.get("value"):
        raise RuntimeError("Public historical page token was not found.")

    resp = s.post(
        PUBLIC_DISTRICT_HISTORY_URL,
        data={
            "stateCode": STATE_CODE,
            "mealServedDate": report_date,
            "__RequestVerificationToken": token.get("value"),
        },
        headers={
            **HEADERS,
            "Referer": PUBLIC_STATE_REPORT_URL,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=50,
    )
    resp.raise_for_status()

    rows = parse_public_historical_districts(resp.text)
    if len(rows) < 25:
        text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True)
        raise RuntimeError(
            f"Public historical district report returned only {len(rows)} district rows; "
            "the result was not cached because it may be incomplete."
            + (f" Source message: {re.sub(r'\\s+', ' ', text)[:220]}" if text else "")
        )

    # Ensure district codes and names are unique before trusting the page.
    codes = [str(r.get("districtCode")) for r in rows]
    names = [normalize_district_name(r.get("district")) for r in rows]
    if len(set(codes)) != len(codes) or len(set(names)) != len(names):
        raise RuntimeError("Historical district response contains duplicate district codes/names.")

    payload = {
        "reportDate": report_date,
        "level": "district",
        "rows": rows,
        "source": "public-official",
        "sourceUrl": resp.url,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "cacheVersion": PUBLIC_HISTORY_CACHE_VERSION,
    }
    save_official_cache(report_date, "district", payload, source_url=resp.url)
    return payload

def recent_public_active_district_days(days=7, end_date=None, refresh=False):
    """Return the most recent active reporting days, skipping state-wide all-zero days."""
    days = max(1, min(int(days), 7))
    if end_date:
        cursor = datetime.strptime(validate_report_date(end_date), "%d/%m/%Y").date()
    else:
        cursor = datetime.now(IST).date() - timedelta(days=1)

    found = []
    attempts = 0
    while len(found) < days and attempts < 35:
        ds = cursor.strftime("%d/%m/%Y")
        try:
            page = fetch_public_district_history(ds, refresh=refresh)
            rows = page.get("rows", [])
            state_reported = sum(to_int(r.get("dailyReported")) for r in rows)
            state_meals = sum(to_int(r.get("mealsServed")) for r in rows)
            # Sundays/holidays/non-reporting dates must not reduce performance averages.
            if rows and (state_reported > 0 or state_meals > 0):
                found.append(page)
        except Exception as exc:
            print("Public history date warning:", ds, exc, flush=True)
        cursor -= timedelta(days=1)
        attempts += 1

    found.reverse()
    return found

def public_district_poor_performers(days=7, district_code=None, limit=200):
    pages = recent_public_active_district_days(days)
    if not pages:
        return {
            "level": "district", "requestedDays": days, "daysTracked": 0,
            "dates": [], "rows": [], "source": "public-official"
        }

    per_code = {}
    for page in pages:
        report_date = page["reportDate"]
        for r in page.get("rows", []):
            if district_code and str(r.get("districtCode")) != str(district_code):
                continue
            code = str(r.get("districtCode"))
            total = to_int(r.get("totalSchools"))
            reported = to_int(r.get("dailyReported"))
            pending = to_int(r.get("dailyNotReported"))
            meals = to_int(r.get("mealsServed"))
            pct_value = (reported * 100.0 / total) if total else 0
            item = per_code.setdefault(code, {
                "entityCode": code,
                "entityName": r.get("district"),
                "districtCode": code,
                "districtName": r.get("district"),
                "blockCode": None, "blockName": None,
                "clusterCode": None, "clusterName": None,
                "points": [],
            })
            item["points"].append({
                "date": report_date,
                "reportingPct": pct_value,
                "pending": pending,
                "meals": meals,
            })

    out = []
    for item in per_code.values():
        pts = item.pop("points")
        tracked = len(pts)
        if not tracked:
            continue
        incomplete = sum(1 for p in pts if p["pending"] > 0)
        avg_pct = sum(p["reportingPct"] for p in pts) / tracked
        worst_pct = min(p["reportingPct"] for p in pts)
        avg_pending = sum(p["pending"] for p in pts) / tracked
        max_pending = max(p["pending"] for p in pts)
        avg_meals = sum(p["meals"] for p in pts) / tracked

        # Keep only entities with an actual historical gap.
        if incomplete == 0 and avg_pct >= 100:
            continue

        if incomplete == tracked and tracked >= 2 and avg_pct < 95:
            status = "High attention"
        elif incomplete >= max(2, (tracked + 1) // 2) or avg_pct < 98:
            status = "Needs follow-up"
        else:
            status = "Occasional gap"

        item.update({
            "daysTracked": tracked,
            "incompleteDays": incomplete,
            "avgReportingPct": round(avg_pct, 2),
            "worstReportingPct": round(worst_pct, 2),
            "avgPending": round(avg_pending, 1),
            "maxPending": int(max_pending),
            "avgMeals": round(avg_meals, 1),
            "status": status,
        })
        out.append(item)

    out.sort(key=lambda r: (-r["incompleteDays"], r["avgReportingPct"], -r["avgPending"]))
    return {
        "level": "district",
        "requestedDays": days,
        "daysTracked": len(pages),
        "dates": [p["reportDate"] for p in pages],
        "rows": out[:max(1, min(int(limit), 500))],
        "source": "public-official",
    }


def public_district_trend(report_dates, district_code, district_name=None, refresh=False):
    points = []
    warnings = []
    expected_norm = normalize_district_name(district_name)

    for report_date in report_dates:
        try:
            page = fetch_public_district_history(report_date, refresh=refresh)
            rows = page.get("rows", [])

            row_by_code = next(
                (r for r in rows if str(r.get("districtCode")) == str(district_code)),
                None,
            )
            row_by_name = next(
                (r for r in rows if expected_norm and normalize_district_name(r.get("district")) == expected_norm),
                None,
            )

            row = row_by_code
            match_method = "district-code"

            # If code and expected district name disagree, prefer the exact district name.
            if district_name and row_by_code and normalize_district_name(row_by_code.get("district")) != expected_norm:
                if row_by_name:
                    row = row_by_name
                    match_method = "district-name-fallback"
                    warnings.append(
                        f"{report_date}: district code {district_code} pointed to "
                        f"{row_by_code.get('district')}; used exact name {district_name} instead."
                    )
                else:
                    points.append({
                        "date": report_date, "available": False,
                        "error": "District code/name mismatch in official response."
                    })
                    continue
            elif not row and row_by_name:
                row = row_by_name
                match_method = "district-name-fallback"
                warnings.append(
                    f"{report_date}: district was found by name because code {district_code} was not present."
                )

            if not row:
                points.append({"date": report_date, "available": False})
                continue

            total = to_int(row.get("totalSchools"))
            reported = to_int(row.get("dailyReported"))
            pending = to_int(row.get("dailyNotReported"))

            # Basic arithmetic integrity check.
            if total and reported + pending != total:
                warnings.append(
                    f"{report_date}: Reported + Pending ({reported + pending}) does not equal Total Schools ({total})."
                )

            points.append({
                "date": report_date,
                "available": True,
                "districtName": row.get("district"),
                "districtCode": row.get("districtCode"),
                "matchMethod": match_method,
                "reportingPct": round((reported * 100.0 / total) if total else 0, 2),
                "totalSchools": total,
                "reported": reported,
                "pending": pending,
                "mealsServed": to_int(row.get("mealsServed")),
                "source": page.get("source", "public-official"),
            })
        except Exception as exc:
            points.append({"date": report_date, "available": False, "error": str(exc)})

    valid = [p for p in points if p.get("available")]

    # Detect suspicious school-total changes across a short trend.
    totals = [p["totalSchools"] for p in valid if p.get("totalSchools")]
    if totals:
        common_total = max(set(totals), key=totals.count)
        for p in valid:
            t = p.get("totalSchools") or 0
            if common_total and abs(t - common_total) / common_total > 0.10:
                warnings.append(
                    f"{p['date']}: Total Schools is {t:,}, while the usual value in this trend is "
                    f"{common_total:,}. Verify this date before using it for analysis."
                )

    # Compare against today's live district reference when possible.
    live_reference = None
    try:
        live_rows = parse_districts()
        live_by_code = next(
            (r for r in live_rows if str(r.get("districtCode")) == str(district_code)),
            None,
        )
        live_by_name = next(
            (r for r in live_rows if expected_norm and normalize_district_name(r.get("district")) == expected_norm),
            None,
        )
        live_reference = live_by_name or live_by_code
        if live_reference and totals:
            live_total = to_int(live_reference.get("totalSchools"))
            common_total = max(set(totals), key=totals.count)
            if live_total and common_total and abs(common_total - live_total) / live_total > 0.15:
                warnings.append(
                    f"Data check: selected district {district_name or district_code} currently has "
                    f"{live_total:,} schools, but the historical trend is showing about {common_total:,}. "
                    "The trend is marked for verification."
                )
    except Exception:
        pass

    return {
        "level": "district",
        "entityCode": district_code,
        "entityName": district_name,
        "points": points,
        "daysAvailable": len(valid),
        "averageReportingPct": round(
            sum(p["reportingPct"] for p in valid) / len(valid), 2
        ) if valid else 0,
        "worstDay": min(valid, key=lambda p: p["reportingPct"]) if valid else None,
        "bestDay": max(valid, key=lambda p: p["reportingPct"]) if valid else None,
        "warnings": list(dict.fromkeys(warnings)),
        "verified": len(warnings) == 0,
        "liveReference": {
            "district": live_reference.get("district"),
            "districtCode": live_reference.get("districtCode"),
            "totalSchools": to_int(live_reference.get("totalSchools")),
        } if live_reference else None,
    }



# -------------------- OFFICIAL PREVIOUS REPORTS --------------------

def validate_report_date(value):
    try:
        dt = datetime.strptime(str(value).strip(), "%d/%m/%Y")
    except Exception:
        raise ValueError("Date must be in DD/MM/YYYY format.")
    today_ist = datetime.now(IST).date()
    if dt.date() > today_ist:
        raise ValueError("Future dates are not allowed.")
    return dt.strftime("%d/%m/%Y")


def official_window_open():
    # The official portal makes backdated reports available after 5 PM.
    # Before 5 PM we only serve pages already saved in our archive.
    now = datetime.now(IST)
    return now.hour >= 17


def history_scope_key(level, district_code=None, block_code=None, cluster_code=None):
    if level == "district":
        return f"state:{STATE_CODE}"
    if level == "block":
        return f"district:{district_code or ''}"
    if level == "cluster":
        return f"block:{block_code or ''}"
    if level == "school":
        return f"cluster:{cluster_code or ''}"
    raise ValueError("level must be district, block, cluster or school")


def load_official_cache(report_date, level, district_code=None, block_code=None, cluster_code=None):
    if not db_enabled():
        return None
    scope_key = history_scope_key(level, district_code, block_code, cluster_code)
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT payload_json,fetched_at,source_url
                FROM official_history_cache
                WHERE report_date=%s AND level=%s AND scope_key=%s
            """, (report_date, level, scope_key))
            row = cur.fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row[0])
    except Exception:
        return None
    payload["source"] = "archive"
    payload["fetchedAt"] = row[1].isoformat()
    payload["sourceUrl"] = row[2]
    return payload


def save_official_cache(report_date, level, payload, district_code=None, block_code=None, cluster_code=None, source_url=None):
    if not db_enabled():
        return
    init_db()
    scope_key = history_scope_key(level, district_code, block_code, cluster_code)
    body = dict(payload)
    body.pop("source", None)
    body.pop("fetchedAt", None)
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO official_history_cache(
                    report_date,level,scope_key,district_code,block_code,cluster_code,source_url,payload_json
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(report_date,level,scope_key) DO UPDATE SET
                    district_code=EXCLUDED.district_code,
                    block_code=EXCLUDED.block_code,
                    cluster_code=EXCLUDED.cluster_code,
                    fetched_at=NOW(),
                    source_url=EXCLUDED.source_url,
                    payload_json=EXCLUDED.payload_json
            """, (
                report_date, level, scope_key, district_code, block_code, cluster_code,
                source_url, json.dumps(body, ensure_ascii=False)
            ))
        conn.commit()


def _history_session(report_date):
    report_date = validate_report_date(report_date)
    s = requests.Session()
    s.headers.update(HEADERS)
    form_url = f"{REPORTS_BASE}/MDM"
    r = s.get(form_url, timeout=40)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    token = soup.find("input", attrs={"name": "__RequestVerificationToken"})
    if not token or not token.get("value"):
        raise RuntimeError("Official report form token was not found.")
    payload = {
        "__RequestVerificationToken": token.get("value"),
        "CDate": report_date,
    }
    r2 = s.post(
        f"{REPORTS_BASE}/MDM/Submit",
        data=payload,
        headers={**HEADERS, "Referer": form_url},
        timeout=50,
        allow_redirects=True,
    )
    r2.raise_for_status()
    # The selected date is stored in the official server session.
    return s


def _extract_href_code(tr, param_name):
    for tag in tr.find_all(["a", "span", "td"]):
        href = tag.get("href") if hasattr(tag, "get") else None
        if href and param_name in href:
            try:
                qs = parse_qs(urlparse(href).query)
                if qs.get(param_name):
                    return qs[param_name][0]
            except Exception:
                pass
        onclick = tag.get("onclick") if hasattr(tag, "get") else None
        if onclick:
            m = re.search(rf"{re.escape(param_name)}\s*=\s*['\\\"]?([0-9]+)", onclick)
            if m:
                return m.group(1)
    return None


def _extract_numeric_code_from_row(tr, min_digits=5):
    text = " ".join([
        str(tag.get("href") or "") + " " + str(tag.get("onclick") or "")
        for tag in tr.find_all(["a", "span", "td"])
    ])
    nums = re.findall(rf"\b18\d{{{max(0,min_digits-2)},}}\b", text)
    return nums[-1] if nums else None


def parse_official_summary_html(html, level, district_code=None, block_code=None, cluster_code=None):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tbody tr"):
        cells = clean_cells(tr)
        if not cells:
            continue

        if level in {"district", "block", "cluster"}:
            if len(cells) < 9:
                continue
            name = cells[1].strip()
            if not name:
                continue
            if level == "district":
                code = _extract_href_code(tr, "districtCode")
            elif level == "block":
                code = _extract_href_code(tr, "blockCode")
            else:
                code = _extract_href_code(tr, "clusterCode")
            if not code:
                code = _extract_numeric_code_from_row(tr, 5) or name
            rows.append({
                level: name,
                f"{level}Code": str(code),
                "totalSchools": to_int(cells[2]),
                "monthlyReported": to_int(cells[3]),
                "monthlyNotReported": to_int(cells[4]),
                "enrolled": to_int(cells[5]),
                "dailyReported": to_int(cells[6]),
                "dailyNotReported": to_int(cells[7]),
                "mealsServed": to_int(cells[8]),
            })
            continue

        # Historical SchoolReports follows the same visible layout as the live school table:
        # School, Shift, Monthly status, Enrolled, Daily status, Meals served.
        if level == "school" and len(cells) >= 7:
            school_name = cells[1].strip()
            if not school_name:
                continue
            code = (
                _extract_href_code(tr, "schoolCode")
                or _extract_numeric_code_from_row(tr, 8)
                or f"{cluster_code or 'cluster'}:{cells[2]}:{school_name}"
            )
            rows.append({
                "school": school_name,
                "schoolCode": str(code),
                "shift": cells[2],
                "monthlyStatus": cells[3],
                "enrolled": to_int(cells[4]),
                "dailyStatus": cells[5],
                "mealsServed": to_int(cells[6]),
            })

    return rows


def official_target(level, district_code=None, block_code=None, cluster_code=None):
    if level == "district":
        return f"{REPORTS_BASE}/DistrictReports", {"stateCode": STATE_CODE}
    if level == "block":
        if not district_code:
            raise ValueError("districtCode is required for block reports.")
        return f"{REPORTS_BASE}/BlockReports", {"stateCode": STATE_CODE, "districtCode": district_code}
    if level == "cluster":
        if not district_code or not block_code:
            raise ValueError("districtCode and blockCode are required for cluster reports.")
        return f"{REPORTS_BASE}/ClusterReports", {
            "stateCode": STATE_CODE, "districtCode": district_code, "blockCode": block_code
        }
    if level == "school":
        if not district_code or not block_code or not cluster_code:
            raise ValueError("districtCode, blockCode and clusterCode are required for school reports.")
        return f"{REPORTS_BASE}/SchoolReports", {
            "stateCode": STATE_CODE, "districtCode": district_code,
            "blockCode": block_code, "clusterCode": cluster_code
        }
    raise ValueError("level must be district, block, cluster or school")


def fetch_official_history_page(report_date, level, district_code=None, block_code=None, cluster_code=None):
    report_date = validate_report_date(report_date)
    s = _history_session(report_date)
    url, params = official_target(level, district_code, block_code, cluster_code)
    r = s.get(url, params=params, timeout=50)
    r.raise_for_status()

    # If the source refuses the report/date, do not attempt to circumvent that restriction.
    # We require an actual report table with parsed rows.
    rows = parse_official_summary_html(r.text, level, district_code, block_code, cluster_code)
    if not rows:
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        short = re.sub(r"\s+", " ", text)[:240]
        raise RuntimeError(
            "Official historical report is not available for this page/date right now."
            + (f" Source message: {short}" if short else "")
        )

    payload = {
        "reportDate": report_date,
        "level": level,
        "rows": rows,
        "source": "official",
        "sourceUrl": r.url,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }
    save_official_cache(
        report_date, level, payload, district_code, block_code, cluster_code, r.url
    )
    return payload


def get_official_history_page(report_date, level, district_code=None, block_code=None, cluster_code=None, refresh=False):
    report_date = validate_report_date(report_date)

    # V6.1: district history uses the public StateWiseSummary -> DisttWiseSummary endpoint.
    if level == "district":
        if refresh and db_enabled():
            # Refresh means re-fetch from source instead of using the cached district page.
            scope_key = history_scope_key("district")
            with db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM official_history_cache WHERE report_date=%s AND level='district' AND scope_key=%s",
                        (report_date, scope_key)
                    )
                conn.commit()
        return fetch_public_district_history(report_date)

    # We intentionally do not guess historical block/cluster/school POST endpoints.
    cached = load_official_cache(report_date, level, district_code, block_code, cluster_code)
    if cached:
        return cached
    raise RuntimeError(
        "District previous reports are connected through the public historical endpoint in V6.1. "
        "Historical Block / Cluster / School public endpoints are not connected yet; "
        "live drill-down is still available."
    )


def official_history_trend(report_dates, level, entity_code, district_code=None, block_code=None, cluster_code=None, entity_name=None, refresh=False):
    if level == "district":
        return public_district_trend(report_dates, entity_code, entity_name, refresh=refresh)
    points = []
    for report_date in report_dates:
        try:
            page = get_official_history_page(
                report_date, level, district_code, block_code, cluster_code
            )
            key = f"{level}Code"
            row = next((x for x in page["rows"] if str(x.get(key)) == str(entity_code)), None)
            if row:
                total = to_int(row.get("totalSchools"))
                reported = to_int(row.get("dailyReported"))
                pending = to_int(row.get("dailyNotReported"))
                meals = to_int(row.get("mealsServed"))
                points.append({
                    "date": report_date,
                    "available": True,
                    "reportingPct": round((reported / total * 100) if total else 0, 2),
                    "totalSchools": total,
                    "reported": reported,
                    "pending": pending,
                    "mealsServed": meals,
                    "source": page.get("source", "official"),
                })
            else:
                points.append({"date": report_date, "available": False})
        except Exception as exc:
            points.append({"date": report_date, "available": False, "error": str(exc)})
    valid = [p for p in points if p.get("available")]
    avg = round(sum(p["reportingPct"] for p in valid) / len(valid), 2) if valid else 0
    worst = min(valid, key=lambda p: p["reportingPct"]) if valid else None
    best = max(valid, key=lambda p: p["reportingPct"]) if valid else None
    return {
        "level": level,
        "entityCode": entity_code,
        "points": points,
        "daysAvailable": len(valid),
        "averageReportingPct": avg,
        "worstDay": worst,
        "bestDay": best,
    }


def archive_official_final(report_date=None, source="manual"):
    if not db_enabled():
        raise RuntimeError("Database is not configured.")
    if not OFFICIAL_ARCHIVE_LOCK.acquire(blocking=False):
        return {"skipped": True, "reason": "An official archive run is already in progress."}
    started = datetime.now(timezone.utc)
    try:
        if report_date is None:
            report_date = datetime.now(IST).strftime("%d/%m/%Y")
        report_date = validate_report_date(report_date)

        page = get_official_history_page(report_date, "district", refresh=True)
        duration = (datetime.now(timezone.utc) - started).total_seconds()

        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO official_archive_runs(
                        report_date,source,district_pages,block_pages,cluster_pages,school_pages,duration_seconds
                    ) VALUES(%s,%s,1,0,0,0,%s)
                    RETURNING id,captured_at
                """, (report_date, source, duration))
                run_id, captured_at = cur.fetchone()
            conn.commit()

        return {
            "skipped": False,
            "runId": run_id,
            "capturedAt": captured_at.isoformat(),
            "reportDate": report_date,
            "districtPages": 1,
            "blockPages": 0,
            "clusterPages": 0,
            "schoolPages": 0,
            "districts": len(page.get("rows", [])),
            "durationSeconds": round(duration, 2),
            "note": "V6.1 archives the public district historical page. Deeper public history endpoints are pending discovery.",
        }
    finally:
        OFFICIAL_ARCHIVE_LOCK.release()

def official_archive_status():
    if not db_enabled():
        return {"configured": False, "latest": None, "cachedPages": 0}
    init_db()
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id,report_date,captured_at,source,district_pages,block_pages,cluster_pages,school_pages,duration_seconds
                FROM official_archive_runs ORDER BY captured_at DESC LIMIT 1
            """)
            row = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM official_history_cache")
            cached = cur.fetchone()[0]
    latest = None
    if row:
        latest = {
            "id": row[0], "reportDate": row[1], "capturedAt": row[2].isoformat(),
            "source": row[3], "districtPages": row[4], "blockPages": row[5],
            "clusterPages": row[6], "schoolPages": row[7], "durationSeconds": float(row[8] or 0)
        }
    return {"configured": True, "latest": latest, "cachedPages": cached}



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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS official_history_cache (
                    report_date TEXT NOT NULL,
                    level TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    district_code TEXT,
                    block_code TEXT,
                    cluster_code TEXT,
                    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    source_url TEXT,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(report_date, level, scope_key)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS ix_official_history_date ON official_history_cache(report_date, level)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS official_archive_runs (
                    id BIGSERIAL PRIMARY KEY,
                    report_date TEXT NOT NULL,
                    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    source TEXT NOT NULL DEFAULT 'manual',
                    district_pages INTEGER NOT NULL DEFAULT 0,
                    block_pages INTEGER NOT NULL DEFAULT 0,
                    cluster_pages INTEGER NOT NULL DEFAULT 0,
                    school_pages INTEGER NOT NULL DEFAULT 0,
                    duration_seconds NUMERIC(10,2) NOT NULL DEFAULT 0
                )
            """)
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
    days=max(1,min(int(days),7)); limit=max(1,min(int(limit),500))

    # V6.1 district analysis comes from the public official date-wise endpoint,
    # so it works immediately without waiting for our tracker to accumulate days.
    if level == "district":
        return public_district_poor_performers(days, district_code, limit)

    if not db_enabled():
        raise RuntimeError("Tracker database is not configured.")
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
                    SELECT school_code,COALESCE(NULLIF(MAX(school_name),''),school_code),COALESCE(NULLIF(MAX(shift_id),''),'1'),
                           MAX(district_code),MAX(district_name),
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
    return jsonify({"ok": True, "service": "assam-mdm-dashboard-v6.2", "trackerDb": db_enabled()})


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



@app.get("/api/official/history/status")
def official_history_status_route():
    try:
        status = official_archive_status()
        status["officialWindowOpen"] = True
        status["publicDistrictHistory"] = True
        status["historicalDrilldown"] = "district-only"
        status["currentIst"] = datetime.now(IST).isoformat()
        return jsonify({"ok": True, "data": status})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/official/history/page")
def official_history_page_route():
    try:
        date = request.args.get("date")
        level = request.args.get("level", "district")
        if not date:
            return jsonify({"ok": False, "error": "date is required in DD/MM/YYYY format"}), 400
        if level not in {"district", "block", "cluster", "school"}:
            return jsonify({"ok": False, "error": "invalid level"}), 400
        data = get_official_history_page(
            date, level,
            request.args.get("districtCode"),
            request.args.get("blockCode"),
            request.args.get("clusterCode"),
            refresh=request.args.get("refresh") == "1",
        )
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 409


@app.get("/api/official/history/trend")
def official_history_trend_route():
    try:
        level = request.args.get("level", "district")
        code = request.args.get("code")
        end_date = request.args.get("endDate")
        days = max(1, min(to_int(request.args.get("days", 7)) or 7, 7))
        if level != "district":
            return jsonify({"ok": False, "error": "V6.1 official previous-report trend is currently available for districts."}), 400
        if not code or not end_date:
            return jsonify({"ok": False, "error": "code and endDate are required"}), 400
        refresh = request.args.get("refresh") == "1"
        if level == "district":
            pages = recent_public_active_district_days(days, end_date, refresh=refresh)
            dates = [p.get("reportDate") for p in pages]
        else:
            end_dt = datetime.strptime(validate_report_date(end_date), "%d/%m/%Y")
            dates = [(end_dt - timedelta(days=i)).strftime("%d/%m/%Y") for i in reversed(range(days))]

        data = official_history_trend(
            dates, level, code,
            request.args.get("districtCode"),
            request.args.get("blockCode"),
            request.args.get("clusterCode"),
            entity_name=request.args.get("name"),
            refresh=False,
        )
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.post("/api/official/archive/final")
def official_archive_final_route():
    try:
        data = archive_official_final(
            request.args.get("date"),
            request.args.get("source", "manual")[:40]
        )
        return jsonify({"ok": True, "data": data})
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
        level = request.args.get("level", "district")
        days = to_int(request.args.get("days", 7)) or 7
        data = historical_poor_performers(
            level, days,
            request.args.get("districtCode"),
            request.args.get("blockCode"),
            500
        )

        buff = io.StringIO()
        buff.write("\ufeff")  # Excel-friendly UTF-8 BOM
        w = csv.writer(buff)
        period = f"Last {data.get('daysTracked', 0)} available days"

        if level == "district":
            w.writerow([
                "Period", "District", "District Code", "Days Observed",
                "Days With Pending Schools", "Average Daily Reporting %",
                "Lowest Daily Reporting %", "Average Pending Schools",
                "Highest Pending Schools", "Follow-up Status"
            ])
            for r in data["rows"]:
                w.writerow([
                    period, r.get("entityName"), r.get("entityCode"),
                    r.get("daysTracked"), r.get("incompleteDays"),
                    r.get("avgReportingPct"), r.get("worstReportingPct"),
                    r.get("avgPending"), r.get("maxPending"), r.get("status")
                ])

        elif level == "block":
            w.writerow([
                "Period", "District", "District Code", "Block", "Block Code",
                "Days Observed", "Days With Pending Schools",
                "Average Daily Reporting %", "Lowest Daily Reporting %",
                "Average Pending Schools", "Highest Pending Schools",
                "Follow-up Status"
            ])
            for r in data["rows"]:
                w.writerow([
                    period, r.get("districtName"), r.get("districtCode"),
                    r.get("entityName"), r.get("entityCode"),
                    r.get("daysTracked"), r.get("incompleteDays"),
                    r.get("avgReportingPct"), r.get("worstReportingPct"),
                    r.get("avgPending"), r.get("maxPending"), r.get("status")
                ])

        elif level == "cluster":
            w.writerow([
                "Period", "District", "District Code", "Block", "Block Code",
                "Cluster", "Cluster Code", "Days Observed",
                "Days With Pending Schools", "Average Daily Reporting %",
                "Lowest Daily Reporting %", "Average Pending Schools",
                "Highest Pending Schools", "Follow-up Status"
            ])
            for r in data["rows"]:
                w.writerow([
                    period, r.get("districtName"), r.get("districtCode"),
                    r.get("blockName"), r.get("blockCode"),
                    r.get("entityName"), r.get("entityCode"),
                    r.get("daysTracked"), r.get("incompleteDays"),
                    r.get("avgReportingPct"), r.get("worstReportingPct"),
                    r.get("avgPending"), r.get("maxPending"), r.get("status")
                ])

        elif level == "school":
            w.writerow([
                "Period", "District", "District Code", "Block", "Block Code",
                "Cluster", "Cluster Code", "School Name", "School Code", "Shift",
                "Days Observed", "Days Not Reported", "Not Reported Rate %",
                "Last Not Reported Date", "Follow-up Status"
            ])
            for r in data["rows"]:
                w.writerow([
                    period, r.get("districtName"), r.get("districtCode"),
                    r.get("blockName"), r.get("blockCode"),
                    r.get("clusterName"), r.get("clusterCode"),
                    r.get("entityName"), r.get("entityCode"), r.get("shift"),
                    data.get("daysTracked"), r.get("missedDays"), r.get("missRate"),
                    r.get("lastGapDate"), r.get("status")
                ])
        else:
            return jsonify({"ok": False, "error": "level must be district, block, cluster or school"}), 400

        filename = f"MDM_Follow_Up_{level}_{days}days.csv"
        return Response(
            buff.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500



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
