"""Rain + tide commute risk scoring (v2).

A rules-based risk WINDOW. Not a flood prediction, not AI, and not validated against
official guidance. Every value marked PLACEHOLDER is a guess: tune it and source it
(IMD / KMC) before claiming accuracy.
"""
import json
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")   # India has no daylight saving

# ---- PLACEHOLDER tuning constants -------------------------------------------------
RAIN_TIERS = [(30, 3), (15, 2), (5, 1)]  # (mm in the departure window, points)
RAIN_MIN_FOR_EXTRAS = 5                  # tide and known-spot points only count above this
TIDE_POINTS = 1
SPOT_POINTS = 0                          # 0 = reported history is shown but adds no points; set to 1 to count it
HIGH_AT, CAUTION_AT = 3, 2               # points -> level
WINDOW_BEFORE_H, WINDOW_AFTER_H = 2, 1   # hours around the departure hour
MIN_HOURS_PRESENT = 3                    # of the 4 window hours, else "Unknown"
TIDE_MARGIN = timedelta(hours=1)

# Open-Meteo hourly precipitation is believed to be the total for the PRECEDING hour (VERIFY in their docs).
PRECIP_IS_PRECEDING_HOUR = True
# -----------------------------------------------------------------------------------

DISCLAIMER = "Risk window from rain and tide times. Not a flood prediction. Check the road before you go."

REPLAY_DANA_NOTE = (
    "Replay uses Open-Meteo modelled rain. For the 24 h to 11:30 IST on 25 Oct 2024 the model shows "
    "about 40 mm; the Alipore Met office recorded over 100 mm (PTI). The model understates this event."
)


def _hour_key(label_dt, source_is_utc):
    local = label_dt
    if source_is_utc:
        local = label_dt.replace(tzinfo=timezone.utc).astimezone(IST).replace(tzinfo=None)
    local = local - timedelta(minutes=30) if PRECIP_IS_PRECEDING_HOUR else local + timedelta(minutes=30)
    return local.replace(minute=0, second=0, microsecond=0)


def load_hourly(api_json, source_is_utc=False):
    out = {}
    for t, mm in zip(api_json["hourly"]["time"], api_json["hourly"]["precipitation"]):
        if mm is None:
            continue
        out[_hour_key(datetime.fromisoformat(t), source_is_utc)] = float(mm)
    return out


def load_tides(path):
    with open(path) as f:
        raw = json.load(f)
    tides = []
    for day, times in raw.items():
        if day.startswith("_"):
            continue
        for t in times:
            try:
                tides.append(datetime.fromisoformat(f"{day}T{t}"))
            except ValueError:
                raise ValueError(f"Bad tide entry {day} {t!r}: use HH:MM, 24-hour, IST")
    return tides


def score(hourly, tides, corridor, depart, rain_word="forecast"):
    window = [depart + timedelta(hours=i) for i in range(-WINDOW_BEFORE_H, WINDOW_AFTER_H + 1)]
    present = [h for h in window if h in hourly]
    if len(present) < MIN_HOURS_PRESENT:
        return {"level": "Unknown", "points": None,
                "reasons": [f"Rain data for only {len(present)} of {len(window)} hours"]}
    rain = sum(hourly[h] for h in present)
    w_start, w_end = window[0], window[-1] + timedelta(hours=1)
    pts = next((p for mm, p in RAIN_TIERS if rain >= mm), 0)
    reasons = [f"{rain:.0f} mm {rain_word} rain {w_start:%H:%M}-{w_end:%H:%M}"]
    if len(present) < len(window):
        reasons.append(f"rain data missing for {len(window) - len(present)} hour(s), so the total may be low")
    if rain >= RAIN_MIN_FOR_EXTRAS:
        near = next((t for t in tides if w_start - TIDE_MARGIN <= t <= w_end + TIDE_MARGIN), None)
        if near:
            pts += TIDE_POINTS
            reasons.append(f"high tide at Garden Reach near {near:%H:%M}; drainage can slow (timing differs elsewhere)")
        elif not tides:
            reasons.append("tide times not loaded, so tide is not counted")
        if corridor.get("chronic_spot") and SPOT_POINTS:
            pts += SPOT_POINTS
            src = corridor.get("source")
            reasons.append(f"known waterlogging spot ({src})" if src else "known waterlogging spot (set by hand)")
    level = "High risk" if pts >= HIGH_AT else "Caution" if pts >= CAUTION_AT else "Lower risk"
    return {"level": level, "points": pts, "rain_mm": round(rain, 1), "reasons": reasons}


def check(hourly, tides, corridor, depart, mode="live", data_note=None):
    rain_word = "forecast" if mode == "live" else "modelled (replay)"
    res = score(hourly, tides, corridor, depart, rain_word)
    if res["points"] is not None and res["level"] in ("Caution", "High risk"):
        alts = []
        for d in range(-4, 5):
            if d == 0:
                continue
            t = depart + timedelta(hours=d)
            r = score(hourly, tides, corridor, t, rain_word)
            if r["points"] is not None:
                alts.append((r["points"], abs(d), t))
        if alts:
            best = min(alts)
            if best[0] < res["points"]:
                res["better_time"] = f"{best[2]:%H:%M} looks lower risk"
    res["mode"] = mode
    res["disclaimer"] = DISCLAIMER
    if data_note:
        res["data_note"] = data_note
    return res
