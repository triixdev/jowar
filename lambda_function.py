"""Jowar: one Lambda behind API Gateway (HTTP API) and an EventBridge schedule.
Routes: GET /corridors, GET /check, POST /feedback.  EventBridge input {"task": "refresh"} refreshes the forecast cache.
Stores only: cached forecasts, and feedback (area, hour, level, yes/no). No names, IPs or locations."""
import json
import os
import re
import time
import traceback
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta

from scoring import IST, check, load_hourly, load_tides, score

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE_NAME = os.environ.get("TABLE_NAME", "rainwatch")
CACHE_SECONDS = 1800
# After deploying the page, set the ALLOWED_ORIGIN environment variable to its address, for example
# https://jowar.vercel.app (no slash at the end). Unset means any site may call the API.
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*").strip().rstrip("/") or "*"
DEPART_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}$")
LEVELS = {"Lower risk", "Caution", "High risk"}

with open(os.path.join(HERE, "corridors.json")) as f:
    CORRIDORS = {c["id"]: c for c in json.load(f)}
TIDES = load_tides(os.path.join(HERE, "tides.json"))
TIDE_DAYS = {t.date() for t in TIDES}
REPLAYS = {}   # past events; an entry is skipped if its data file is not in the zip
with open(os.path.join(HERE, "replays.json")) as f:
    for _r in json.load(f):
        _p = os.path.join(HERE, _r["file"])
        if os.path.exists(_p):
            with open(_p) as g:
                _h = load_hourly(json.load(g), source_is_utc=_r.get("source_is_utc", False))
            REPLAYS[_r["id"]] = {**_r, "hourly": _h, "dates": sorted(d for d in {k.date().isoformat() for k in _h}
                                                 if sum(1 for k in _h if k.date().isoformat() == d) >= 12)}

_table = None


class BadRequest(Exception):
    pass


def now_ist():
    return datetime.now(IST).replace(tzinfo=None)


def get_table():
    global _table
    if _table is None:
        import boto3
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def fetch_forecast(corridor):
    q = urllib.parse.urlencode({
        "latitude": corridor["lat"], "longitude": corridor["lon"], "hourly": "precipitation",
        "timezone": "Asia/Kolkata", "past_days": 1, "forecast_days": 3})
    with urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q, timeout=8) as r:
        data = json.load(r)
    return {"times": data["hourly"]["time"], "rain": data["hourly"]["precipitation"]}


def _store(cid, payload):
    get_table().put_item(Item={"pk": "forecast", "sk": cid, "fetched_at": int(time.time()), "data": json.dumps(payload)})


def get_hourly(cid):
    """Returns (hourly dict, fetched_at epoch, stale flag). Uses the cache; falls back to an old copy if Open-Meteo fails."""
    item = get_table().get_item(Key={"pk": "forecast", "sk": cid}).get("Item")
    if item and time.time() - int(item["fetched_at"]) < CACHE_SECONDS:
        payload, fetched, stale = json.loads(item["data"]), int(item["fetched_at"]), False
    else:
        try:
            payload = fetch_forecast(CORRIDORS[cid])
            _store(cid, payload)
            fetched, stale = int(time.time()), False
        except Exception:
            if not item:
                raise
            payload, fetched, stale = json.loads(item["data"]), int(item["fetched_at"]), True
    hourly = load_hourly({"hourly": {"time": payload["times"], "precipitation": payload["rain"]}})
    return hourly, fetched, stale


def refresh():
    done = []
    for cid, c in CORRIDORS.items():
        try:
            _store(cid, fetch_forecast(c))
            done.append(cid)
        except Exception:
            print("refresh failed for", cid)
            traceback.print_exc()
    return {"refreshed": done}


def parse_depart(s, mode, replay=None):
    if not s or not DEPART_RE.match(s):
        raise BadRequest("depart must look like 2026-10-12T09")
    try:
        d = datetime.strptime(s, "%Y-%m-%dT%H")
    except ValueError:
        raise BadRequest("depart is not a real date and hour")
    if mode == "replay":
        if replay is None or d.date().isoformat() not in replay["dates"]:
            raise BadRequest("pick a date inside the replay event")
    else:
        n = now_ist()
        if not (n - timedelta(hours=3) <= d <= n + timedelta(hours=70)):
            raise BadRequest("pick a time from 3 hours ago to about 3 days ahead")
    return d


def build_result(cid, depart, mode, replay=None):
    c = CORRIDORS[cid]
    extra = {}
    if mode == "replay":
        hourly, tides, note = replay["hourly"], [], replay["note"]
    else:
        hourly, fetched, stale = get_hourly(cid)
        tides, note = TIDES, None
        extra["fetched_at"] = datetime.fromtimestamp(fetched, IST).strftime("%Y-%m-%d %H:%M IST")
        if stale:
            extra["data_note"] = "Showing an older saved forecast because the weather service did not respond."
    res = check(hourly, tides, c, depart, mode=mode, data_note=note)
    if mode == "live" and depart.date() not in TIDE_DAYS:
        res["reasons"].append("no tide table loaded for this date, so tide is not counted")
    res.update(extra)
    rain_word = "forecast" if mode == "live" else "modelled (replay)"
    day0 = depart.replace(hour=0)
    res["strip"] = []
    for h in range(24):
        r = score(hourly, tides, c, day0 + timedelta(hours=h), rain_word)
        res["strip"].append({"hour": h, "level": r["level"], "rain": r.get("rain_mm")})
    res["high_tides"] = [t.strftime("%H:%M") for t in tides if t.date() == depart.date()]
    res["area"] = c["name"]
    res["history"] = c.get("reported", [])
    return res


def resp(status, body):
    headers = {"Content-Type": "application/json", "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
               "Access-Control-Allow-Headers": "content-type", "Access-Control-Allow-Methods": "GET,POST,OPTIONS"}
    if ALLOWED_ORIGIN != "*":
        headers["Vary"] = "Origin"
    return {"statusCode": status, "headers": headers, "body": json.dumps(body) if body != "" else ""}


def handle_check(params):
    cid, mode = params.get("corridor"), params.get("mode", "live")
    if cid not in CORRIDORS:
        raise BadRequest("unknown area")
    if mode not in ("live", "replay"):
        raise BadRequest("mode must be live or replay")
    replay = None
    if mode == "replay":
        replay = REPLAYS.get(params.get("replay") or next(iter(REPLAYS), ""))
        if replay is None:
            raise BadRequest("unknown replay event")
    return build_result(cid, parse_depart(params.get("depart"), mode, replay), mode, replay)


def handle_feedback(raw):
    if raw is None or len(raw) > 2000:
        raise BadRequest("bad body")
    try:
        b = json.loads(raw)
    except ValueError:
        raise BadRequest("body must be JSON")
    if not isinstance(b, dict):
        raise BadRequest("body must be an object")
    cid, level, flooded = b.get("corridor"), b.get("level"), b.get("flooded")
    if cid not in CORRIDORS or level not in LEVELS or not isinstance(flooded, bool):
        raise BadRequest("corridor, level and flooded (true/false) are required")
    d = parse_depart(b.get("depart"), "live")
    if d > now_ist():
        raise BadRequest("feedback is only for hours that have already started")
    get_table().put_item(Item={"pk": f"feedback#{cid}", "sk": f"{now_ist():%Y-%m-%dT%H:%M:%S}#{uuid.uuid4().hex[:6]}",
                               "depart": d.strftime("%Y-%m-%dT%H"), "level": level, "flooded": flooded})
    return {"saved": True}


def lambda_handler(event, context=None):
    if event.get("task") == "refresh":
        return refresh()
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", "GET"), event.get("rawPath", "/")
    if method == "OPTIONS":
        return resp(204, "")
    try:
        if method == "GET" and path.endswith("/corridors"):
            return resp(200, [{"id": c["id"], "name": c["name"]} for c in CORRIDORS.values()])
        if method == "GET" and path.endswith("/replays"):
            return resp(200, [{"id": r["id"], "name": r["name"], "date": r["date"], "dates": r["dates"],
                               "default_hour": r["default_hour"]} for r in REPLAYS.values()])
        if method == "GET" and path.endswith("/check"):
            return resp(200, handle_check(event.get("queryStringParameters") or {}))
        if method == "POST" and path.endswith("/feedback"):
            return resp(200, handle_feedback(event.get("body")))
        return resp(404, {"error": "not found"})
    except BadRequest as e:
        return resp(400, {"error": str(e)})
    except Exception:
        traceback.print_exc()
        return resp(500, {"error": "Something went wrong. Try again in a minute."})
