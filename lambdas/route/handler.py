"""CHHAYA routing handler — Phase 3 (CLAUDE.md §7.7, §6.5/§6.6, §8.2/§8.3).

Events (HTTP API v2 payload):
  POST /route        -> per-route compute, direct | shade | flood (task contract)
  GET  /route/stats  -> graph summary per §6.6 ({area, n_edges, n_nodes, bbox,
                        slots, seasons, weights})
  GET  /route        -> {"ok": true}  Phase 0 smoke contract (§10 done-when), unchanged
  POST /advice       -> 501 — Bedrock is Phase 6-optional per the decision sheet;
                        the path is reserved with no model ID anywhere (rule: never
                        hardcode a Bedrock model id; it is runtime-discovered in Phase 6).

Request body:
  origin / destination : [lon, lat] WGS84 (the brief's "destination"; §6.5's
                         "dest" is accepted as an alias)
  mode                 : "direct" | "shade" | "flood"   (required)
  season               : "summer" | "monsoon" (default: monsoon for flood, else summer)
  time                 : IST "HH:MM" or "now" (§8.3: slot = round((min - 07:00)/15),
                         clamped 0..47; clamped=true is reported)

Response 200 keys: route, distance_m, duration_s (env WALK_SPEED_MPS, default
1.1 m/s — the Phase 3 brief overrides §6.6's 1.3), shade_profile[48],
shade_score, flood_profile, mode, season, slot (+ slot_time, clamped).

Errors: 400 {"error": "bad_request" | "outside_coverage" | "no_route"}.
outside_coverage carries the loaded coverage polygon (§6.3). Engine/infra
failures return 500 with a loud log — never a swallowed error.

DEPLOYMENT NOTE: the routing bundle (graph.pkl + shade/flood arrays + coverage)
must be uploaded to the GraphBucket (pipeline/upload.py) before the first POST —
the cold-start loader fails loudly otherwise; docs/BLOCKERS.md owns the
creds-pending row.
"""

from __future__ import annotations

import base64
import json
import time
import traceback
from datetime import datetime, timedelta, timezone

import cost
import routing

# IST = UTC+5:30 fixed, no DST (§6.1).
IST = timezone(timedelta(hours=5, minutes=30))
SLOT_START_MINUTES = 7 * 60  # 07:00 IST (§6.2)

_ADVICE_501 = {"error": "not_implemented", "detail": "/advice arrives in Phase 6"}


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
    clamped = raw_slot < 0 or raw_slot > cost.SLOTS - 1
    slot = max(0, min(cost.SLOTS - 1, raw_slot))
    slot_time = (
        datetime(2000, 1, 1, tzinfo=IST)
        + timedelta(minutes=SLOT_START_MINUTES + slot * 15)
    ).strftime("%H:%M")
    return slot, slot_time, clamped


def lambda_handler(event, context):
    method = ((event.get("requestContext") or {}).get("http") or {}).get(
        "method", "GET"
    )
    path = event.get("rawPath") or ""
    route_key = event.get("routeKey") or f"{method} {path}"
    normalized = path.rstrip("/")

    try:
        if normalized.endswith("/route/stats") and method == "GET":
            return _handle_stats()
        if normalized.endswith("/route") and method == "POST":
            return _handle_route(event)
        if normalized.endswith("/advice"):
            return _json(501, _ADVICE_501)
        if normalized.endswith("/route") and method == "GET":
            return _json(200, {"ok": True})  # Phase 0 deploy smoke test (§10)
        return _json(404, {"error": "not_found", "detail": route_key})
    except routing.OutsideCoverage as exc:
        return _json(400, {"error": "outside_coverage", "coverage": exc.coverage})
    except routing.NoRoute as exc:
        return _json(400, {"error": "no_route", "detail": str(exc)})
    except Exception:  # noqa: BLE001 — a Lambda must answer the API, loudly, with logs
        print("UNHANDLED routing error:\n" + traceback.format_exc())
        return _json(500, {"error": "internal_error"})


def _handle_stats() -> dict:
    started = time.monotonic()
    payload = routing.get_engine().stats()
    _emit_emf(
        "StatsLatencyMs",
        (time.monotonic() - started) * 1000,
        {"Mode": "stats", "Season": "-"},
    )
    return _json(200, payload)


def _handle_route(event) -> dict:
    started = time.monotonic()

    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise TypeError("body must be a JSON object")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
        return _json(400, {"error": "bad_request", "detail": f"invalid body: {exc}"})

    origin = _parse_point(body.get("origin"), "origin")
    if isinstance(origin, dict):
        return origin
    dest_key = next((k for k in ("destination", "dest") if k in body), None)
    if dest_key is None:
        return _json(400, {"error": "bad_request", "detail": "missing destination"})
    destination = _parse_point(body[dest_key], "destination")
    if isinstance(destination, dict):
        return destination

    mode = body.get("mode")
    if mode not in cost.MODES:
        return _json(
            400,
            {
                "error": "bad_request",
                "detail": f"mode must be one of {list(cost.MODES)}",
            },
        )
    season = body.get("season") or ("monsoon" if mode == "flood" else "summer")
    if season not in cost.SEASONS:
        return _json(
            400,
            {
                "error": "bad_request",
                "detail": f"season must be one of {list(cost.SEASONS)}",
            },
        )

    time_str = body.get("time", "now")
    try:
        slot, slot_time, clamped = slot_from_time(time_str)
    except (ValueError, AttributeError) as exc:
        return _json(
            400,
            {
                "error": "bad_request",
                "detail": f"time must be IST 'HH:MM' or 'now': {exc}",
            },
        )

    payload = routing.get_engine().route(mode, season, slot, origin, destination)
    payload["slot_time"] = slot_time
    payload["clamped"] = clamped

    _emit_emf(
        "RouteLatencyMs",
        (time.monotonic() - started) * 1000,
        {"Mode": mode, "Season": season},
    )
    if routing.cold_start_ms is not None:
        _emit_emf(
            "ColdStartMs", routing.cold_start_ms, {"Mode": mode, "Season": season}
        )
        routing.cold_start_ms = None  # one cold-start metric per container
    return _json(200, payload)


def _parse_point(value, name: str):
    """Returns (lon, lat) floats, or an error-response dict to short-circuit with."""
    if not isinstance(value, list) or len(value) != 2:
        return _json(
            400, {"error": "bad_request", "detail": f"{name} must be [lon, lat]"}
        )
    lon, lat = value
    if (
        isinstance(lon, bool)
        or isinstance(lat, bool)
        or not all(isinstance(v, (int, float)) for v in (lon, lat))
    ):
        return _json(
            400,
            {"error": "bad_request", "detail": f"{name} must be numeric [lon, lat]"},
        )
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return _json(
            400, {"error": "bad_request", "detail": f"{name} outside WGS84 range"}
        )
    return float(lon), float(lat)


def _emit_emf(metric_name: str, value_ms: float, dims: dict) -> None:
    """CloudWatch EMF line — no powertools dependency (§0 rule 5)."""
    print(
        json.dumps(
            {
                "_aws": {
                    "TimestampMillis": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "chhaya",
                            "Dimensions": [["Service", "Mode", "Season"]],
                            "Metrics": [{"Name": metric_name, "Unit": "Milliseconds"}],
                        }
                    ],
                },
                "Service": "chhaya-route",
                **dims,
                metric_name: round(value_ms, 1),
            }
        )
    )


def _json(status_code: int, payload: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload, ensure_ascii=False),
    }
