"""CHHAYA Phase 5 — PrecomputeHandler Lambda stub (§10 Phase 5, §7.9 shade pipeline).

The MVP's shade compute runs OFFLINE (pipeline/shade.py + pipeline/build_graph.py),
so this handler is the Step Functions step that a future real compute slot replaces.
Task contract for the stub:

  * Event (the state-machine-mediated ingest contract — the SAME bucket/key env
    names the route Lambda reads, so a real compute can swipe in unchanged):
        {"season": "summer"|"monsoon", "GRAPH_BUCKET": ..., "S3_KEY_GRAPH": ...}
  * Validates the event, then reads the routing bundle's header via
    S3 head_object (ContentLength > 0 — the MVP minimums gate; the full §7.6
    array checks stay local in pipeline/build_graph.py, which runs before upload).
  * Writes a manifest document to s3://<GRAPH_BUCKET>/manifest/<season>.json.
  * Returns {"status", "season", "manifest_key", "GRAPH_BUCKET", "S3_KEY_GRAPH",
    "graph_size_bytes"}.
  * Failures raise PrecomputeError (kinds: bad_request | minimums_not_met |
    s3_error) — surfaced by Step Functions as States.TaskFailed and routed to the
    state machine's Fail state (the §7.9 notify signal on the dashboard).

Errors are RAISED, never returned as 200-with-error-bodies: this handler is
Step-Functions-mediated, not HTTP, so its caller is the state machine, not a web
client (docs/DECISIONS.md).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger("chhaya.precompute_handler")

# §6.2 allowed season terms — no ARN validation in code (the brief lists §6.2 as
# the source of the season set); the state machine validates by structure.
SEASONS: tuple[str, ...] = ("summer", "monsoon")
MANIFEST_PREFIX = "manifest/"

_ERROR_KINDS: tuple[str, ...] = ("bad_request", "minimums_not_met", "s3_error")


class PrecomputeError(RuntimeError):
    """Operational precompute failure — one of the documented kinds."""

    def __init__(self, kind: str, detail: str) -> None:
        if kind not in _ERROR_KINDS:
            raise ValueError(f"PrecomputeError kind must be one of {_ERROR_KINDS}, got {kind!r}")
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def _s3_client() -> Any:
    return boto3.client("s3")


def validate_bundle_event(event: dict[str, Any]) -> tuple[str, str, str]:
    """Validate the ingest contract; returns (season, GRAPH_BUCKET, S3_KEY_GRAPH).

    The bucket/key names must match the route Lambda's env-var contract exactly
    (lambdas/route/routing.py: GRAPH_BUCKET + S3_KEY_GRAPH) — that is what makes
    the swap-in of a real compute a no-op on the state machine.
    """
    season = event.get("season")
    if season not in SEASONS:
        raise PrecomputeError("bad_request", f"season must be one of {SEASONS}, got {season!r}")
    bucket = event.get("GRAPH_BUCKET")
    if not isinstance(bucket, str) or not bucket:
        raise PrecomputeError("bad_request", "GRAPH_BUCKET must be a non-empty string")
    graph_key = event.get("S3_KEY_GRAPH")
    if not isinstance(graph_key, str) or not graph_key:
        raise PrecomputeError("bad_request", "S3_KEY_GRAPH must be a non-empty string")
    return season, bucket, graph_key


def head_bundle_length(bucket: str, key: str) -> int:
    """Head the routing bundle; returns its ContentLength (> 0) or raises.

    head_object response shape verified against the boto3 S3 client doc
    (docs/DECISIONS.md): the body-size field is ``ContentLength`` (int).
    """
    client = _s3_client()
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "") or "unknown"
        raise PrecomputeError(
            "minimums_not_met",
            f"routing bundle s3://{bucket}/{key} not readable (s3 error code {code})",
        ) from err
    size = int(head.get("ContentLength", 0))
    if size <= 0:
        raise PrecomputeError(
            "minimums_not_met",
            f"routing bundle s3://{bucket}/{key} has zero content-length",
        )
    return size


def write_manifest(bucket: str, season: str, graph_key: str, graph_size: int) -> str:
    """Write the idempotent per-season manifest; returns its s3:// URI."""
    client = _s3_client()
    manifest_key = f"{MANIFEST_PREFIX}{season}.json"
    document = {
        "status": "ok",
        "season": season,
        "GRAPH_BUCKET": bucket,
        "S3_KEY_GRAPH": graph_key,
        "graph_size_bytes": graph_size,
    }
    try:
        client.put_object(
            Bucket=bucket,
            Key=manifest_key,
            Body=json.dumps(document).encode("utf-8"),
            ContentType="application/json",
        )
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "") or "unknown"
        raise PrecomputeError(
            "s3_error", f"manifest write s3://{bucket}/{manifest_key} failed (s3 error code {code})"
        ) from err
    return f"s3://{bucket}/{manifest_key}"


def run(event: dict[str, Any]) -> dict[str, Any]:
    """One precompute step: validate -> head-check -> manifest -> return."""
    season, bucket, graph_key = validate_bundle_event(event)
    graph_size = head_bundle_length(bucket, graph_key)
    manifest_key = write_manifest(bucket, season, graph_key, graph_size)
    return {
        "status": "ok",
        "season": season,
        "GRAPH_BUCKET": bucket,
        "S3_KEY_GRAPH": graph_key,
        "graph_size_bytes": graph_size,
        "manifest_key": manifest_key,
    }


def lambda_handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """Entry point wired in infra/template.yaml (Handler: handler.lambda_handler)."""
    LOG.info("precompute invoked for event keys: %s", sorted(event or {}))
    return run(event)
