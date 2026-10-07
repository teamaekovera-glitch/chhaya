#!/usr/bin/env python3
"""CHHAYA Phase 2 — S3 artifact upload (§3 / §6.3 / §6.4 artefact set).

GUARDED: this module is ready-but-creds-pending (docs/BLOCKERS.md). It refuses
to run unless BOTH
    GRAPH_BUCKET   env var (target bucket; config.S3_BUCKET is the default
                   bucket name but the env var is the explicit go-signal)
    AWS credentials (boto3 default chain: env / profile / STS)
are present, and it performs a dry-run listing by default (--execute to send).
No bytes leave this machine unless the operator passes --execute explicitly.

Upload set (bucket layout mirrors the Lambda's expected keys):
    graph/graph.pkl          upload-only artifact (multi-MB pickle, gitignored)
    graph/nodes.npz          committed-sized, but single source is data/
    graph/coverage.geojson
    arrays/buildings.npz     §6.4 ragged arrays (Lambda shade pipeline input)
    arrays/edges.npz
    shade/summer.npy         float16 (E, 48) per §6.4
    shade/monsoon.npy
    flood/flood.npy          float16 per-edge flood_risk in edge_id order

Run:    python upload.py            (dry-run: lists what WOULD be uploaded)
        python upload.py --execute  (actual upload; requires creds + GRAPH_BUCKET)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import S3_BUCKET  # default bucket name; env var is the go-signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("upload")

DATA = ROOT / "data"

# (local path, bucket key) — the §3 / §6.3 / §6.4 artefact set
UPLOAD_SET: list[tuple[str, str]] = [
    ("graph.pkl", "graph/graph.pkl"),
    ("nodes.npz", "graph/nodes.npz"),
    ("coverage.geojson", "graph/coverage.geojson"),
    ("buildings.npz", "arrays/buildings.npz"),
    ("edges.npz", "arrays/edges.npz"),
    ("shade_summer.npy", "shade/summer.npy"),
    ("shade_monsoon.npy", "shade/monsoon.npy"),
    ("flood.npy", "flood/flood.npy"),
]


def plan(bucket: str) -> list[tuple[Path, int, str]]:
    """Existing artifacts with sizes and their bucket keys; abort loudly on gaps."""
    planned: list[tuple[Path, int, str]] = []
    missing: list[str] = []
    for name, key in UPLOAD_SET:
        path = DATA / name
        if not path.exists():
            missing.append(name)
            continue
        planned.append((path, path.stat().st_size, key))
    if missing:
        raise FileNotFoundError(
            f"artifacts not built yet: {missing} — run the pipeline stages first"
        )
    log.info("upload plan for s3://%s (%d objects):", bucket, len(planned))
    for path, size, key in planned:
        log.info("  %-24s %10.1f KiB  ->  s3://%s/%s", path.name, size / 1024, bucket, key)
    return planned


def upload(bucket: str, execute: bool) -> None:
    import boto3  # imported late: dry-run must not require credentials

    planned = plan(bucket)
    if not execute:
        log.info("DRY-RUN: %d objects scoped, nothing uploaded (pass --execute to send)", len(planned))
        return
    try:
        client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-south-1"))
        client.head_bucket(Bucket=bucket)
    except Exception as exc:  # creds absent, bucket absent, or no network
        log.error("cannot reach s3://%s (%s: %s) — upload aborted, nothing sent",
                  bucket, type(exc).__name__, exc)
        raise SystemExit(2) from exc
    for path, size, key in planned:
        client.upload_file(str(path), bucket, key)
        log.info("uploaded s3://%s/%s (%.1f KiB)", bucket, key, size / 1024)
    log.info("DONE: %d objects live on s3://%s", len(planned), bucket)


def main() -> None:
    ap = argparse.ArgumentParser(description="CHHAYA artifact upload to S3 (guarded)")
    ap.add_argument("--execute", action="store_true",
                    help="actually upload (default: dry-run listing)")
    args = ap.parse_args()
    bucket = os.environ.get("GRAPH_BUCKET", "").strip()
    if not bucket:
        log.error(
            "GRAPH_BUCKET env var is not set — refusing to run. Export it (the "
            "default bucket name from config.py is %r, but the env var is the "
            "explicit go-signal) once AWS credentials exist.", S3_BUCKET
        )
        raise SystemExit(2)
    if not os.environ.get("AWS_REGION"):
        os.environ["AWS_REGION"] = "ap-south-1"
    upload(bucket, args.execute)


if __name__ == "__main__":
    main()
