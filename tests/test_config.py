"""Sanity tests for pipeline/config.py — the Phase 0 contract anchor (CLAUDE.md §6, §8.1)."""

from pipeline import config


def test_bbox_order_is_west_south_east_north():
    w, s, e, n = config.BBOX
    assert w < e and s < n


def test_bbox_is_the_locked_karol_bagh_one():
    assert config.BBOX == (77.178, 28.642, 77.208, 28.657)
    assert config.AREA_NAME == "Karol Bagh"


def test_utm_zone_matches_the_bbox_centroid():
    lon_centroid = (config.BBOX[0] + config.BBOX[2]) / 2
    zone = int((lon_centroid + 180) // 6) + 1
    assert config.UTM_EPSG == 32600 + zone
    assert config.UTM_EPSG == 32643  # locked at kickoff (§6.1)


def test_weights_match_contract_8_1():
    assert config.WEIGHTS["summer"] == {"a_shade": 2.0, "a_flood": 0.0, "a_under": 0.0}
    assert config.WEIGHTS["monsoon"] == {"a_shade": 0.5, "a_flood": 4.0, "a_under": 5.0}


def test_slots_and_season_dates_match_section_6_2():
    assert config.SLOTS == 48
    assert config.SLOT_START_MINUTES == 7 * 60
    assert config.SEASON_DATES == {"summer": "2026-05-15", "monsoon": "2026-07-15"}
