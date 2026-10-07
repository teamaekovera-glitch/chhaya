"""CHHAYA Phase 5 — PrecomputeHandler stub tests (task briefs c/d/g).

Fully unit-testable without AWS credentials (task contract): two layers.
  * ``botocore.stub.Stubber`` for the S3-error mapping tests, and
  * a pytest-local ``_FakeS3`` client for the end-to-end runs, which records
    ``put_object`` bodies so the manifest document can be asserted exactly.

The synthetic pickle fixture (brief g) is a real ``networkx.MultiDiGraph``
pickled to bytes in tmp, so the handler's full path (validate -> head ->
manifest -> return) executes against real artifact bytes without touching the
network.
"""
from __future__ import annotations

import importlib.util
import json
import pickle
import sys
from pathlib import Path
from typing import Any

import boto3
import networkx as nx
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

ROOT = Path(__file__).resolve().parent.parent

MODULE_NAME = "chhaya_precompute_handler"
HANDLER_PATH = ROOT / "lambdas" / "precompute_handler" / "handler.py"


def _s3_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "HeadObject" if code != "AccessDenied" else "PutObject",
    )


class _FakeS3:
    """Minimal in-memory S3 client for offline handler runs (records bodies)."""

    def __init__(self, objects: dict[str, bytes], fail_on: set[str] | None = None) -> None:
        self.objects = dict(objects)
        self.calls: list[tuple[str, str]] = []
        self.fail_on = fail_on or set()

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.calls.append(("head_object", f"s3://{Bucket}/{Key}"))
        if "head" in self.fail_on:
            raise _s3_error("AccessDenied", 403)
        body = self.objects.get(Key)
        if body is None:
            raise _s3_error("NoSuchKey", 404)
        return {"ContentLength": len(body), "ETag": '"fake"'}

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str) -> dict[str, Any]:
        self.calls.append(("put_object", f"s3://{Bucket}/{Key}"))
        if "put" in self.fail_on:
            raise _s3_error("AccessDenied", 403)
        self.objects[Key] = bytes(Body)
        return {"ETag": '"fake"'}

    def manifest(self, season: str, bucket: str = "synthetic") -> dict[str, Any]:
        return json.loads(self.objects[f"manifest/{season}.json"].decode("utf-8"))


@pytest.fixture(scope="module", name="handler")
def handler_module():
    """Load lambdas/precompute_handler/handler.py under a unique module name.

    The route lambda also exposes a module named ``handler`` in this pytest
    session (tests/test_route_api.py imports it by that name), so a same-named
    plain import here would collide — load by path under a distinct name.
    """
    if MODULE_NAME in sys.modules:
        return sys.modules[MODULE_NAME]
    spec = importlib.util.spec_from_file_location(MODULE_NAME, HANDLER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def stubbed_s3(monkeypatch, handler):
    """Replace the handler's s3 factory with a Stubber-managed client."""
    client = boto3.client("s3")
    stubber = Stubber(client)
    monkeypatch.setattr(handler, "_s3_client", lambda: client)
    return stubber


def make_valid_event(bucket: str = "synthetic", key: str = "graph/graph.pkl") -> dict[str, Any]:
    return {"season": "summer", "GRAPH_BUCKET": bucket, "S3_KEY_GRAPH": key}


@pytest.fixture(name="synthetic_pickle")
def synthetic_pickle_fixture() -> dict[str, Any]:
    """A connected 21-node bidirectional chain graph pickled to bytes (brief g)."""
    graph = nx.MultiDiGraph()
    for i in range(21):
        graph.add_node(i, x=77.18 + i * 1e-3, y=28.64, x_m=float(i) * 10, y_m=0.0)
    for i in range(20):
        graph.add_edge(i, i + 1, length_m=10.0, highway="residential")
        graph.add_edge(i + 1, i, length_m=10.0, highway="residential")
    blob = pickle.dumps(graph, protocol=5)
    return {"blob": blob, "size": len(blob)}


@pytest.fixture(name="fake_s3")
def fake_s3_fixture(monkeypatch, handler, synthetic_pickle: dict) -> _FakeS3:
    """FakeS3 pre-seeded with the synthetic pickle at the routing bundle key."""
    fake = _FakeS3({"graph/graph.pkl": synthetic_pickle["blob"]})
    monkeypatch.setattr(handler, "_s3_client", lambda: fake)
    return fake


# ------------------------------------------------------------- ingest validation


@pytest.mark.parametrize(
    "event",
    [
        {},  # nothing at all
        {"season": "winter", "GRAPH_BUCKET": "b", "S3_KEY_GRAPH": "k"},  # not a §6.2 season
        {"GRAPH_BUCKET": "b", "S3_KEY_GRAPH": "k"},  # season missing
        {"season": "summer", "S3_KEY_GRAPH": "k"},  # bucket missing
        {"season": "summer", "GRAPH_BUCKET": "b"},  # key missing
        {"season": "summer", "GRAPH_BUCKET": "", "S3_KEY_GRAPH": "k"},  # empty bucket
    ],
    ids=["empty", "bad-season", "no-season", "no-bucket", "no-key", "empty-bucket"],
)
def test_validate_rejects_bad_ingest_events(handler, event: dict) -> None:
    with pytest.raises(handler.PrecomputeError) as err:
        handler.validate_bundle_event(event)
    assert err.value.kind == "bad_request"


# ------------------------------------------------------------------- head checks


def test_head_bundle_length_returns_positive_size(handler, stubbed_s3) -> None:
    stubbed_s3.add_response(
        "head_object",
        {"ContentLength": 1_234},
        {"Bucket": "synthetic", "Key": "graph/graph.pkl"},
    )
    with stubbed_s3:
        size = handler.head_bundle_length("synthetic", "graph/graph.pkl")
    stubbed_s3.assert_no_pending_responses()
    assert size == 1_234


def test_head_bundle_length_rejects_zero_length(handler, stubbed_s3) -> None:
    stubbed_s3.add_response(
        "head_object", {"ContentLength": 0}, {"Bucket": "synthetic", "Key": "graph/graph.pkl"}
    )
    with stubbed_s3, pytest.raises(handler.PrecomputeError) as err:
        handler.head_bundle_length("synthetic", "graph/graph.pkl")
    stubbed_s3.assert_no_pending_responses()
    assert err.value.kind == "minimums_not_met"


def test_head_bundle_length_maps_s3_404(handler, stubbed_s3) -> None:
    stubbed_s3.add_client_error("head_object", service_error_code="NoSuchKey", http_status_code=404)
    with stubbed_s3, pytest.raises(handler.PrecomputeError) as err:
        handler.head_bundle_length("b", "k")
    stubbed_s3.assert_no_pending_responses()
    assert err.value.kind == "minimums_not_met"
    assert "NoSuchKey" in err.value.detail


# ----------------------------------------------------------------- manifest write


def test_write_manifest_maps_put_failure_to_s3_error(handler, stubbed_s3) -> None:
    stubbed_s3.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)
    with stubbed_s3, pytest.raises(handler.PrecomputeError) as err:
        handler.write_manifest("b", "summer", "graph/graph.pkl", 100)
    stubbed_s3.assert_no_pending_responses()
    assert err.value.kind == "s3_error"


# ---------------------------------------------------------------- end-to-end runs


def test_run_against_synthetic_pickle_writes_exact_manifest(
    handler, fake_s3: _FakeS3, synthetic_pickle: dict
) -> None:
    """Brief (g): full handler run against the LOCAL synthetic pickle fixture —
    validates, heads the real pickled bytes, and writes the manifest exactly."""
    result = handler.lambda_handler(make_valid_event())

    assert result["status"] == "ok"
    assert result["season"] == "summer"
    assert result["GRAPH_BUCKET"] == "synthetic"
    assert result["S3_KEY_GRAPH"] == "graph/graph.pkl"
    assert result["manifest_key"] == "s3://synthetic/manifest/summer.json"
    assert result["graph_size_bytes"] == synthetic_pickle["size"]

    assert [c[0] for c in fake_s3.calls] == ["head_object", "put_object"]
    document = fake_s3.manifest("summer")
    assert document == {
        "status": "ok",
        "season": "summer",
        "GRAPH_BUCKET": "synthetic",
        "S3_KEY_GRAPH": "graph/graph.pkl",
        "graph_size_bytes": synthetic_pickle["size"],
    }


def test_run_is_idempotent_for_the_same_season(handler, fake_s3: _FakeS3) -> None:
    """Same season twice -> identical manifest key, manifest simply rewritten."""
    first = handler.lambda_handler(make_valid_event())
    second = handler.lambda_handler(make_valid_event())
    assert first["manifest_key"] == second["manifest_key"] == "s3://synthetic/manifest/summer.json"
    assert fake_s3.objects["manifest/summer.json"] == fake_s3.objects["manifest/summer.json"]


def test_run_both_seasons_writes_two_manifests(handler, fake_s3: _FakeS3) -> None:
    summer = handler.run(make_valid_event())
    monsoon = handler.run({**make_valid_event(), "season": "monsoon"})
    assert summer["manifest_key"].endswith("manifest/summer.json")
    assert monsoon["manifest_key"].endswith("manifest/monsoon.json")
    assert fake_s3.manifest("monsoon")["season"] == "monsoon"
    assert fake_s3.manifest("summer")["season"] == "summer"


@pytest.mark.parametrize(
    "event",
    [
        {"season": "spring", "GRAPH_BUCKET": "b", "S3_KEY_GRAPH": "k"},
        {"season": "summer", "GRAPH_BUCKET": "b"},  # key missing -> reject first
    ],
    ids=["bad-season", "missing-key"],
)
def test_bad_requests_are_rejected_before_any_s3_call(handler, stubbed_s3, event: dict) -> None:
    with pytest.raises(handler.PrecomputeError):
        handler.lambda_handler(event)
    # Stubber holds no queued responses — any s3 attempt would raise StubAssertionError.
    stubbed_s3.assert_no_pending_responses()


def test_run_raises_when_bundle_missing(handler, fake_s3: _FakeS3) -> None:
    with pytest.raises(handler.PrecomputeError) as err:
        handler.run(make_valid_event(key="graph/absent.pkl"))
    assert err.value.kind == "minimums_not_met"
    assert [c[0] for c in fake_s3.calls] == ["head_object"]


def test_run_raises_when_manifest_put_denied(monkeypatch, handler) -> None:
    fake = _FakeS3({"graph/graph.pkl": b"x" * 128}, fail_on={"put"})
    monkeypatch.setattr(handler, "_s3_client", lambda: fake)
    with pytest.raises(handler.PrecomputeError) as err:
        handler.run(make_valid_event())
    assert err.value.kind == "s3_error"
    assert [c[0] for c in fake.calls] == ["head_object", "put_object"]


def test_run_raises_when_bundle_not_readable(monkeypatch, handler) -> None:
    fake = _FakeS3({"graph/graph.pkl": b"x" * 128}, fail_on={"head"})
    monkeypatch.setattr(handler, "_s3_client", lambda: fake)
    with pytest.raises(handler.PrecomputeError) as err:
        handler.run(make_valid_event())
    assert err.value.kind == "minimums_not_met"
    assert [c[0] for c in fake.calls] == ["head_object"]
