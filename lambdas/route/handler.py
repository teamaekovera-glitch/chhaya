"""CHHAYA routing handler — Phase 0 stub (CLAUDE.md §10, Phase 0).

GET  /route -> {"ok": true}  (deploy smoke test).
POST /route -> the §6.5 response contract shell: request parsing, slot mapping (§8.3)
and validation only. The real route compute (numpy + networkx, graph from S3) lands in Phase 3.

Runtime deps are declared in requirements.txt (numpy, networkx) per §0 rule 5 but are
deliberately NOT imported here — the stub must deploy and answer before the heavy
deps are exercised.
"""

import json
from datetime import datetime, timedelta, timezone

# IST = UTC+5:30 fixed, no DST (§6.1).
IST = timezone(timedelta(hours=5, minutes=30))
SLOT_START_MINUTES = 7 * 60  # 07:00 IST (§6.2)
SLOTS = 48
_VALID_MODES = ("summer", "monsoon")


def slot_from_time(time_str: str) -> tuple[int, str, bool]:
    """§8.3: slot = round(minutes_since_07:00 / 15), clamped to 0..47.

    Accepts IST 'HH:MM' or 'now'. Returns (slot, slot_time, clamped).
    """
    if time_str == "now":
        now = datetime.now(IST)
        minutes = now.hour * 60 + now.minute
    else:
        hh, mm = time_str.split(":")
        minutes = int(hh) * 60 + int(mm)

    raw_slot = round((minutes - SLOT_START_MINUTES) / 15)
    clamped = raw_slot < 0 or raw_slot > SLOTS - 1
    slot = max(0, min(SLOTS - 1, raw_slot))
    slot_time = (
        datetime(2000, 1, 1, tzinfo=IST) + timedelta(minutes=SLOT_START_MINUTES + slot * 15)
    ).strftime("%H:%M")
    return slot, slot_time, clamped


def lambda_handler(event, context):
    method = (event.get("requestContext", {}) or {}).get("http", {}).get("method", "GET")

    if method != "POST":
        return _json(200, {"ok": True})

    try:
        body = json.loads(event.get("body") or "{}")
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        return _json(400, {"error": "bad_request", "detail": f"invalid body: {exc}"})

    mode = body.get("mode", "summer")
    if mode not in _VALID_MODES:
        return _json(400, {"error": "bad_request", "detail": "mode must be 'summer' or 'monsoon'"})

    try:
        slot, slot_time, clamped = slot_from_time(body.get("time", "now"))
    except (ValueError, TypeError):
        return _json(400, {"error": "bad_request", "detail": "time must be IST 'HH:MM' or 'now'"})

    # §6.5 contract shell — direct / chhaya / baseline / delta are filled in Phase 3.
    return _json(
        200,
        {
            "mode": mode,
            "slot": slot,
            "slot_time": slot_time,
            "clamped": clamped,
            "direct": None,
            "chhaya": None,
            "baseline": None,
            "delta": None,
            "summary_en": "Route compute arrives in Phase 3.",
            "summary_hi": "रूट गणना फेज़ 3 में।",
        },
    )


def _json(status_code: int, payload: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload),
    }
