"""Run: python test_handler.py   (no AWS, no network: fake table, fake forecast)"""
import json
from datetime import datetime
import lambda_function as L


class FakeTable:
    def __init__(self): self.items = {}
    def get_item(self, Key): return {"Item": self.items[(Key["pk"], Key["sk"])]} if (Key["pk"], Key["sk"]) in self.items else {}
    def put_item(self, Item): self.items[(Item["pk"], Item["sk"])] = Item


NOW = datetime(2026, 10, 11, 10, 0)
calls = {"n": 0, "fail": False}


def fake_fetch(c):
    calls["n"] += 1
    if calls["fail"]:
        raise RuntimeError("down")
    times = [f"2026-10-{d:02d}T{h:02d}:00" for d in (10, 11, 12, 13) for h in range(24)]
    rain = [20.0 if (t.startswith("2026-10-11") and t[11:13] in ("12", "13", "14")) else 0.0 for t in times]
    return {"times": times, "rain": rain}


def setup():
    L._table = FakeTable(); L.now_ist = lambda: NOW; L.fetch_forecast = fake_fetch
    calls["n"] = 0; calls["fail"] = False


def get(path, **q):
    return L.lambda_handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": path, "queryStringParameters": q})


def post(path, body):
    return L.lambda_handler({"requestContext": {"http": {"method": "POST"}}, "rawPath": path, "body": body})


def test_corridors():
    setup(); r = get("/corridors"); assert r["statusCode"] == 200 and len(json.loads(r["body"])) == 8


def test_live_check_with_tide_is_high_risk():
    setup(); r = get("/check", corridor="behala", depart="2026-10-11T13")
    b = json.loads(r["body"]); assert r["statusCode"] == 200
    assert b["level"] == "High risk", b
    assert any("high tide" in x for x in b["reasons"]) and b["history"] and not any("known waterlogging" in x for x in b["reasons"])
    assert len(b["strip"]) == 24 and b["high_tides"] == ["01:19", "13:33"] and "fetched_at" in b


def test_dry_hour_is_lower_risk():
    setup(); b = json.loads(get("/check", corridor="park-street-circus", depart="2026-10-11T22")["body"]); assert b["level"] == "Lower risk"


def test_cache_prevents_second_fetch():
    setup(); get("/check", corridor="behala", depart="2026-10-11T13"); get("/check", corridor="behala", depart="2026-10-11T14")
    assert calls["n"] == 1


def test_stale_cache_used_when_api_down():
    setup(); get("/check", corridor="behala", depart="2026-10-11T13")
    key = ("forecast", "behala"); L._table.items[key]["fetched_at"] = 1; calls["fail"] = True
    b = json.loads(get("/check", corridor="behala", depart="2026-10-11T13")["body"])
    assert "older saved forecast" in b["data_note"]


def test_api_down_and_no_cache_is_500_without_details():
    setup(); calls["fail"] = True; r = get("/check", corridor="behala", depart="2026-10-11T13")
    assert r["statusCode"] == 500 and "Traceback" not in r["body"]


def test_replay_is_labelled_and_has_no_tide():
    setup(); b = json.loads(get("/check", corridor="behala", mode="replay", replay="dana-2024", depart="2024-10-25T11")["body"])
    assert "replay" in b["reasons"][0] and "understates" in b["data_note"] and b["high_tides"] == []
    assert calls["n"] == 0
    # default replay is the first available event
    b2 = json.loads(get("/check", corridor="behala", mode="replay", depart="2024-10-25T11")["body"]); assert b2["level"] == b["level"]


def test_replays_list_and_missing_file_is_skipped():
    setup(); r = json.loads(get("/replays")["body"])
    ids = [x["id"] for x in r]; assert "dana-2024" in ids
    import os
    assert ("sep-2025" in ids) == os.path.exists("replay_sep2025.json")   # only listed once its data file is added
    assert get("/check", corridor="behala", mode="replay", replay="nope", depart="2024-10-25T11")["statusCode"] == 400


def test_validation():
    setup()
    assert get("/check", corridor="nope", depart="2026-10-11T13")["statusCode"] == 400
    assert get("/check", corridor="behala", depart="tomorrow")["statusCode"] == 400
    assert get("/check", corridor="behala", depart="2026-10-30T13")["statusCode"] == 400
    assert get("/check", corridor="behala", mode="replay", replay="dana-2024", depart="2024-10-20T13")["statusCode"] == 400
    assert get("/check", corridor="behala", mode="x", depart="2026-10-11T13")["statusCode"] == 400


def test_feedback_saved_and_validated():
    setup()
    ok = post("/feedback", json.dumps({"corridor": "behala", "depart": "2026-10-11T09", "level": "Caution", "flooded": True}))
    assert ok["statusCode"] == 200
    item = [v for k, v in L._table.items.items() if k[0].startswith("feedback#")][0]
    assert set(item) == {"pk", "sk", "depart", "level", "flooded"}      # nothing personal is stored
    for bad in ["{}", "[]", "nope", json.dumps({"corridor": "behala", "depart": "2026-10-11T09", "level": "Caution", "flooded": "yes"}),
                json.dumps({"corridor": "behala", "depart": "2026-10-11T09", "level": "Scary", "flooded": True}), "x" * 3000]:
        assert post("/feedback", bad)["statusCode"] == 400
    future = post("/feedback", json.dumps({"corridor": "behala", "depart": "2026-10-11T13", "level": "Caution", "flooded": True}))
    assert future["statusCode"] == 400   # an hour that has not started yet cannot be reported


def test_cors_origin_default_open_and_lockable():
    setup(); assert get("/corridors")["headers"]["Access-Control-Allow-Origin"] == "*"
    L.ALLOWED_ORIGIN = "https://jowar.vercel.app"
    try:
        h = get("/corridors")["headers"]
        assert h["Access-Control-Allow-Origin"] == "https://jowar.vercel.app" and h["Vary"] == "Origin"
    finally:
        L.ALLOWED_ORIGIN = "*"


def test_refresh_task_and_unknown_route():
    setup(); assert len(L.lambda_handler({"task": "refresh"})["refreshed"]) == 8
    assert get("/nothing")["statusCode"] == 404


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests: t(); print("ok  ", t.__name__)
    print(f"{len(tests)} tests passed")
