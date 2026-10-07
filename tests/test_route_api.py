"""Phase 3 routing API tests (task contract + CLAUDE.md §6.5/§6.6, §7.7, §8.1-§8.3).

Two bundle tiers:
  * exact divergences/distance assertions run ONLY on the deterministic
    prepare_fixtures synthetic graph (the real graph.pkl varies with OSM data);
  * contract-shape/stats/error tests accept EITHER the real data/ bundle
    (when graph.pkl exists locally) or the fixture — engine behaviour is
    bundle-independent.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ROUTE = ROOT / "lambdas" / "route"
if str(ROUTE) not in sys.path:
    sys.path.insert(0, str(ROUTE))

import cost
import handler
import prepare_fixtures
import routing

from pipeline import config


@pytest.fixture(scope="session", name="fixture_dir")
def fixture_dir(tmp_path_factory) -> Path:
    return prepare_fixtures.write_fixtures(tmp_path_factory.mktemp("chhaya_fixtures"))


@pytest.fixture(scope="session", name="bundle_dir")
def bundle_dir(fixture_dir: Path) -> Path:
    """The real precompute bundle if built, else the deterministic fixture."""
    real = ROOT / "data"
    return real if (real / "graph.pkl").exists() else fixture_dir


@pytest.fixture()
def api(monkeypatch, bundle_dir: Path):
    """Reset the singleton and point it at the session bundle via the
    local-dir loader (AWS/S3 never exercised here)."""
    routing.reset_engine()
    monkeypatch.setenv("CHHAYA_LOCAL_DATA_DIR", str(bundle_dir))
    monkeypatch.setenv("WALK_SPEED_MPS", "1.1")
    yield handler
    routing.reset_engine()


@pytest.fixture()
def fixture_api(monkeypatch, fixture_dir: Path):
    """Handler pointed at the deterministic fixture (exact-number assertions)."""
    routing.reset_engine()
    monkeypatch.setenv("CHHAYA_LOCAL_DATA_DIR", str(fixture_dir))
    monkeypatch.setenv("WALK_SPEED_MPS", "1.1")
    yield handler
    routing.reset_engine()


def post(api, body: dict, path: str = "/route", method: str = "POST") -> dict:
    event = {
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "body": json.dumps(body),
    }
    resp = api.lambda_handler(event, None)
    return {"status": resp["statusCode"], "body": json.loads(resp["body"])}


# -- §8.1 weights pinning --------------------------------------------------------


def test_weights_pinned_to_config():
    """The Lambda cannot import pipeline/ — the dict-literal copy in cost.py
    must stay exactly equal to the source of truth (change config first, §0 rule 4)."""
    assert cost.WEIGHTS == config.WEIGHTS


def test_area_and_bbox_pinned_to_config():
    assert routing.AREA_NAME == config.AREA_NAME
    assert tuple(routing.BBOX) == tuple(config.BBOX)


# -- cost matrix build (§8.1: (E, 48) float32, built once at load) ---------------


@pytest.fixture()
def fixture_engine(fixture_dir: Path):
    return routing.load_engine_from_dir(fixture_dir, walk_speed_mps=1.1)


def test_cost_matrix_shape_dtype_and_lower_bound(fixture_engine):
    eng = fixture_engine
    for season in cost.SEASONS:
        for m in (eng.shade_cost[season], eng.flood_cost[season]):
            assert m.shape == (eng.n_edges, cost.SLOTS)
            assert m.dtype.name == "float32"
            # §8.1: cost >= length_m at every slot + season
            assert (m >= eng.lengths[:, None] - 1e-6).all()


def test_shade_cost_prefers_shaded_edges(fixture_engine):
    """Same length, different shade: the exposed edge must cost strictly more
    (guards the §8.1 (1 - shade) sign; the brief's literal plus-shade term
    would invert this route preference)."""
    eng = fixture_engine
    ids = {name: i for i, d in enumerate(eng._edge_attr) if (name := d.get("name"))}
    exposed, shaded = ids["Main Road"], ids["Bazar Road"]
    slot = 24
    assert eng.lengths[exposed] == eng.lengths[shaded]
    assert (
        eng.shade_cost["summer"][shaded, slot] < eng.shade_cost["summer"][exposed, slot]
    )
    assert (
        eng.shade_cost["monsoon"][shaded, slot]
        < eng.shade_cost["monsoon"][exposed, slot]
    )


def test_flood_cost_is_slot_invariant_and_rises_with_risk(fixture_engine):
    eng = fixture_engine
    m = eng.flood_cost["monsoon"]
    assert (m == m[:, [0]]).all()  # every column identical
    ids = {name: i for i, d in enumerate(eng._edge_attr) if (name := d.get("name"))}
    assert m[ids["Bazar Low"], 0] > m[ids["Bazar Road"], 0]
    assert m[ids["Bazar Low"], 0] == pytest.approx(120.0 * (1 + 4.0 * 0.9), rel=1e-3)


# -- route divergence (deterministic fixture only) --------------------------------

_NODE0 = prepare_fixtures.node_xy(0)
_NODE2 = prepare_fixtures.node_xy(2)
_NODE5 = prepare_fixtures.node_xy(5)
_NODE7 = prepare_fixtures.node_xy(7)


def test_direct_vs_shade_diverge_on_shaded_bypass(fixture_api):
    origin, dest = list(_NODE0), list(_NODE2)
    body = {"origin": origin, "destination": dest, "time": "15:30"}
    direct = post(fixture_api, {**body, "mode": "direct", "season": "summer"})
    shade = post(fixture_api, {**body, "mode": "shade", "season": "summer"})

    assert direct["status"] == 200 and shade["status"] == 200
    assert direct["body"]["distance_m"] == pytest.approx(
        240.0
    )  # main road incl. underpass
    assert shade["body"]["distance_m"] == pytest.approx(
        440.0
    )  # shaded bypass v1/b1/b2/v6
    assert direct["body"]["route"] != shade["body"]["route"]
    # the shaded bypass was baked lighter than the exposed main road at 15:30,
    # so the shade mode's headline score must beat direct's
    assert shade["body"]["shade_score"] > direct["body"]["shade_score"]


def test_underpass_excluded_in_flood_monsoon(fixture_api):
    body = {
        "origin": list(_NODE0),
        "destination": list(_NODE2),
        "time": "15:30",
        "mode": "flood",
        "season": "monsoon",
    }
    monsoon = post(fixture_api, body)

    assert monsoon["status"] == 200
    # safe detour: v1 + v2 + c1 + c2 + v7 + v6 with the underpass hard-skipped
    assert monsoon["body"]["distance_m"] == pytest.approx(640.0)


def test_underpass_is_a_routing_decision_not_data_removal(fixture_engine):
    eng = fixture_engine
    underpass = next(i for i, d in enumerate(eng._edge_attr) if d.get("is_underpass"))
    assert eng.underpass[underpass]
    # direct mode still takes the 240 m corridor through the underpass;
    # only flood+monsoon routing excludes it
    p_direct = eng.route("direct", "summer", 24, _NODE0, _NODE2)
    assert p_direct["distance_m"] == pytest.approx(240.0)


def test_flood_mode_switches_off_flooded_edge(fixture_api):
    origin, dest = list(_NODE5), list(_NODE7)
    direct = post(
        fixture_api,
        {"origin": origin, "destination": dest, "time": "15:30", "mode": "direct"},
    )
    flood = post(
        fixture_api,
        {
            "origin": origin,
            "destination": dest,
            "time": "15:30",
            "mode": "flood",
            "season": "monsoon",
        },
    )
    assert direct["status"] == 200 and flood["status"] == 200
    # (1,0)->(1,2): direct takes the 240 m corridor across the 0.9-flood edge;
    # flood mode detours via the row-2 corridor 5->10->11->12->7 — same 440 m
    # as the naive bypass but with zero flood exposure on every edge.
    assert direct["body"]["distance_m"] == pytest.approx(240.0)
    assert flood["body"]["distance_m"] == pytest.approx(440.0)
    assert flood["body"]["flood_profile"]["monsoon"] == pytest.approx(0.0)


def test_no_route_returns_400(fixture_api):
    # fixture node (0,4) has no outgoing directed edges
    origin = list(prepare_fixtures.node_xy(4))
    resp = post(
        fixture_api,
        {
            "origin": origin,
            "destination": list(_NODE0),
            "mode": "direct",
            "time": "15:30",
        },
    )
    assert resp["status"] == 400
    assert resp["body"]["error"] == "no_route"


# -- response contract shape (§6.5) ------------------------------------------------

_EXPECTED_KEYS = {
    "route",
    "distance_m",
    "duration_s",
    "shade_profile",
    "shade_score",
    "flood_profile",
    "mode",
    "season",
    "slot",
    "slot_time",
    "clamped",
}


@pytest.mark.parametrize("mode", ["direct", "shade", "flood"])
def test_response_contract_shape(api, mode: str):
    resp = post(
        api,
        {
            "origin": [77.190, 28.645],
            "destination": [77.1925, 28.6451],
            "time": "15:30",
            "mode": mode,
        },
    )
    assert resp["status"] == 200
    body = resp["body"]
    assert set(body) == _EXPECTED_KEYS
    assert body["mode"] == mode
    assert body["season"] in ("summer", "monsoon")
    assert isinstance(body["slot"], int) and 0 <= body["slot"] <= 47
    assert body["slot_time"] == "15:30"
    assert body["clamped"] is False
    assert isinstance(body["distance_m"], (int, float)) and body["distance_m"] > 0
    assert body["duration_s"] == pytest.approx(
        body["distance_m"] / float(os.environ["WALK_SPEED_MPS"])
    )
    profile = body["shade_profile"]
    assert isinstance(profile, list) and len(profile) == 48
    assert all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in profile)
    assert body["shade_score"] == pytest.approx(profile[body["slot"]])
    assert set(body["flood_profile"]) == {"summer", "monsoon"}
    assert all(0.0 <= v <= 1.0 for v in body["flood_profile"].values())
    coords = body["route"]
    assert len(coords) >= 2
    assert all(
        isinstance(p, list) and len(p) == 2 and -90 <= p[1] <= 90 for p in coords
    )  # [lon, lat] pairs


# -- stats endpoint (§6.6 / brief item b) -------------------------------------------


def test_stats_contract_shape(api):
    resp = post(api, {}, path="/route/stats", method="GET")
    assert resp["status"] == 200
    body = resp["body"]
    assert set(body) == {
        "area",
        "n_edges",
        "n_nodes",
        "bbox",
        "slots",
        "seasons",
        "weights",
    }
    assert body["area"] == config.AREA_NAME
    assert body["bbox"] == list(config.BBOX)
    assert body["slots"] == 48
    assert body["seasons"] == ["summer", "monsoon"]
    assert body["weights"] == config.WEIGHTS
    assert isinstance(body["n_edges"], int) and body["n_edges"] > 0
    assert isinstance(body["n_nodes"], int) and body["n_nodes"] > 0


def test_stats_counts_match_the_labelled_bundle(fixture_api):
    resp = post(fixture_api, {}, path="/route/stats", method="GET")
    assert resp["body"]["n_edges"] == 30
    assert resp["body"]["n_nodes"] == 20


# -- error handling ------------------------------------------------------------------


def test_bad_mode_returns_400(api):
    resp = post(
        api,
        {
            "origin": [77.192, 28.6475],
            "destination": [77.1930, 28.6452],
            "mode": "scenic",
        },
    )
    assert resp["status"] == 400
    assert resp["body"]["error"] == "bad_request"
    assert "mode" in resp["body"]["detail"]


def test_bad_season_returns_400(api):
    resp = post(
        api,
        {
            "origin": [77.192, 28.6475],
            "destination": [77.1930, 28.6452],
            "mode": "shade",
            "season": "winter",
        },
    )
    assert resp["status"] == 400
    assert resp["body"]["error"] == "bad_request"


def test_bad_time_returns_400(api):
    resp = post(
        api,
        {
            "origin": [77.192, 28.6475],
            "destination": [77.1930, 28.6452],
            "mode": "direct",
            "time": "noonish",
        },
    )
    assert resp["status"] == 400
    assert resp["body"]["error"] == "bad_request"


def test_outside_coverage_returns_400_with_polygon(api):
    resp = post(
        api,
        {"origin": [77.30, 28.70], "destination": [77.1930, 28.6452], "mode": "direct"},
    )
    assert resp["status"] == 400
    body = resp["body"]
    assert body["error"] == "outside_coverage"
    assert body["coverage"]["type"] in ("FeatureCollection", "Feature", "Polygon")


def test_missing_destination_returns_400(api):
    resp = post(api, {"origin": [77.192, 28.6475], "mode": "direct"})
    assert resp["status"] == 400
    assert resp["body"]["error"] == "bad_request"


def test_dest_alias_accepted(api):
    dest = [77.190 + 2.4e-3, 28.645]
    a = post(
        api,
        {"origin": [77.190, 28.645], "dest": dest, "mode": "direct", "time": "15:30"},
    )
    b = post(
        api,
        {
            "origin": [77.190, 28.645],
            "destination": dest,
            "mode": "direct",
            "time": "15:30",
        },
    )
    assert a["status"] == b["status"] == 200
    assert a["body"]["distance_m"] == b["body"]["distance_m"]


def test_non_numeric_coords_return_400(api):
    resp = post(
        api,
        {
            "origin": ["west", 28.645],
            "destination": [77.1930, 28.6452],
            "mode": "direct",
        },
    )
    assert resp["status"] == 400
    assert resp["body"]["error"] == "bad_request"


# -- slot mapping (§8.3) --------------------------------------------------------------


def test_time_clamped_to_daylight_window(fixture_api):
    origin, dest = list(_NODE0), list(_NODE2)
    early = post(
        fixture_api,
        {"origin": origin, "destination": dest, "mode": "direct", "time": "05:00"},
    )
    late = post(
        fixture_api,
        {"origin": origin, "destination": dest, "mode": "direct", "time": "23:30"},
    )
    assert early["body"]["slot"] == 0 and early["body"]["clamped"] is True
    assert late["body"]["slot"] == 47 and late["body"]["clamped"] is True


def test_slot_mapping_matches_8_3(api):
    resp = post(
        api,
        {
            "origin": [77.190, 28.645],
            "destination": [77.1902, 28.645],
            "mode": "direct",
            "time": "07:15",
        },
    )
    assert resp["body"]["slot"] == 1  # 15 minutes past 07:00


# -- env wiring ------------------------------------------------------------------------


def test_walk_speed_env_overrides_duration(monkeypatch, fixture_dir):
    routing.reset_engine()
    monkeypatch.setenv("CHHAYA_LOCAL_DATA_DIR", str(fixture_dir))
    monkeypatch.setenv("WALK_SPEED_MPS", "2.2")
    try:
        resp = post(
            handler,
            {
                "origin": list(_NODE0),
                "destination": list(_NODE2),
                "mode": "direct",
                "time": "15:30",
            },
        )
        assert resp["body"]["duration_s"] == pytest.approx(240.0 / 2.2)
    finally:
        routing.reset_engine()


def test_phase0_smoke_get_route_untouched(api):
    resp = post(api, {}, path="/route", method="GET")
    assert resp == {"status": 200, "body": {"ok": True}}


def test_unknown_path_404(api):
    resp = post(api, {}, path="/nope", method="GET")
    assert resp["status"] == 404


def test_advice_reserved_501(api):
    resp = post(api, {}, path="/advice")
    assert resp["status"] == 501


# -- LRU warm cache (task contract) ------------------------------------------------------


def test_route_cache_returns_consistent_repeats(fixture_api):
    body = {
        "origin": list(_NODE0),
        "destination": list(_NODE2),
        "mode": "shade",
        "season": "summer",
        "time": "15:30",
    }
    first = post(fixture_api, body)
    second = post(fixture_api, body)
    assert first["body"]["distance_m"] == second["body"]["distance_m"]
    engine = routing.get_engine()
    assert engine._route_cached.cache_info().hits >= 1


def test_spot_duration_and_distance_arithmetic(fixture_api):
    resp = post(
        fixture_api,
        {
            "origin": list(_NODE0),
            "destination": list(_NODE2),
            "mode": "direct",
            "time": "15:30",
        },
    )
    body = resp["body"]
    assert body["distance_m"] == pytest.approx(240.0)
    assert body["duration_s"] == pytest.approx(240.0 / 1.1)
    assert math.isclose(body["shade_score"], body["shade_profile"][body["slot"]])
