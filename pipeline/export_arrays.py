#!/usr/bin/env python3
"""CHHAYA Phase 2 — Lambda-pipeline arrays per §6.4: buildings.npz / edges.npz.

Produced with ``shapely.to_ragged_array`` and consumed in Phase 5 with
``shapely.from_ragged_array`` — the Lambda never needs shapely's file IO or
pyproj: geometry comes back as ragged arrays in UTM (EPSG:32643) and the 2x3
affine carries the UTM frame so coordinates convert without a CRS library.

shapely 2.2 ragged triple, persisted npz-key by npz-key:
    geometry_type  top-level GeometryType enum (as int64)
    coords_index   (n_coords, 2) array mapping coordinates to parts
    types_0..N     the API's third return (a 1-tuple of offsets for pure lines,
                   a 2-tuple of (type_codes, offsets) for polygons/hybrids),
                   saved slot by slot with n_types carrying the arity
    + payload keys: height_m (buildings) / edge_id, width_m (edges)
    + header values: utm_epsg, affine (2x3), n_geometries

Round-trip load (Lambda side, Phase 5):
    gtype = shapely.GeometryType(int(z["geometry_type"]))
    types = tuple(z[f"types_{i}"] for i in range(int(z["n_types"])))
    geoms = shapely.from_ragged_array(gtype, z["coords_index"], types)

Run:    python export_arrays.py
Out:    data/buildings.npz, data/edges.npz
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import shapely

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import UTM_EPSG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export_arrays")

DATA = ROOT / "data"

# 2x3 affine of the UTM frame carried for the Lambda (§6.4): unit scale at the
# natural origin — downstream code can rescale/translate without pyproj.
UTM_AFFINE_2X3 = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])


def _ragged_payload(geom_values, extra: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    gtype, coords_index, types = shapely.to_ragged_array(geom_values)
    payload: dict[str, np.ndarray] = {
        "geometry_type": np.int64(gtype),
        "coords_index": np.asarray(coords_index),
        "n_types": np.int64(len(types)),
        "utm_epsg": np.int64(UTM_EPSG),
        "affine": UTM_AFFINE_2X3,
    }
    # arity varies: 1 for pure linework (offsets only), 2 for polygons
    for i, arr in enumerate(types):
        payload[f"types_{i}"] = np.asarray(arr)
    payload.update(extra)
    return payload


def _roundtrip_load(npz_path: Path):
    """The exact Phase 5 load path, asserted here against the written bytes."""
    with np.load(npz_path) as z:
        n_types = int(z["n_types"])
        types = tuple(z[f"types_{i}"] for i in range(n_types))
        return shapely.from_ragged_array(
            shapely.GeometryType(int(z["geometry_type"])),
            z["coords_index"],
            types,
        )


def export_arrays() -> dict:
    from pipeline.build_graph import width_for
    from pipeline.shade import load_full_area

    buildings, edges = load_full_area()

    b_out = DATA / "buildings.npz"
    np.savez_compressed(b_out, **_ragged_payload(
        buildings.geometry.values,
        {
            "height_m": buildings["height_m"].to_numpy(dtype=np.float32),
            "n_geometries": np.int64(len(buildings)),
        },
    ))
    log.info("wrote %s (%d buildings, %.1f MiB)",
             b_out, len(buildings), b_out.stat().st_size / 1048576)

    edge_ids = (
        edges["edge_id"].to_numpy(dtype=np.int64)
        if "edge_id" in edges.columns
        else np.arange(len(edges), dtype=np.int64)
    )
    widths = np.array([width_for(h) for h in edges["highway"].values], dtype=np.float32)
    e_out = DATA / "edges.npz"
    np.savez_compressed(e_out, **_ragged_payload(
        edges.geometry.values,
        {
            "edge_id": edge_ids,
            "width_m": widths,
            "n_geometries": np.int64(len(edges)),
        },
    ))
    log.info("wrote %s (%d edges, %.1f MiB)", e_out, len(edges), e_out.stat().st_size / 1048576)

    # Round-trip proof on the actual written bytes: from_ragged_array must
    # restore geometry directly from the npz payload (§6.4 contract).
    restored_b = _roundtrip_load(b_out)
    assert len(restored_b) == len(buildings), "round-trip restored wrong building count"
    assert shapely.is_valid(restored_b).all(), "round-trip produced invalid geometries"
    assert np.allclose(
        shapely.area(restored_b), shapely.area(buildings.geometry.values), rtol=0, atol=1e-6
    ), "round-trip areas drift - ragged schema mismatch"
    restored_e = _roundtrip_load(e_out)
    assert len(restored_e) == len(edges), "round-trip restored wrong edge count"
    assert np.allclose(
        shapely.length(restored_e), shapely.length(edges.geometry.values), rtol=0, atol=1e-6
    ), "round-trip lengths drift - ragged schema mismatch"
    log.info("round-trip from_ragged_array: %d buildings + %d edges restored, geometry matches",
             len(restored_b), len(restored_e))

    return {"buildings": len(buildings), "edges": len(edges),
            "buildings_npz_bytes": b_out.stat().st_size, "edges_npz_bytes": e_out.stat().st_size}


if __name__ == "__main__":
    stats = export_arrays()
    log.info("export stats: %s", stats)
