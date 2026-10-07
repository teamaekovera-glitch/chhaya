"""CLAUDE.md §9 solar-accuracy gates — numpy NOAA vs pvlib (TEST-ONLY dep).

Standalone: no network, no OSM data, no AWS credentials. pvlib is a test-only
dependency (§0 rule 5 — it must never enter a Lambda); these tests are the one
place it is imported. The §9 gate: max abs error < 0.5° in altitude AND
azimuth, for both season dates × all 48 slots (07:00–18:45 IST).

IST → UTC conversion happens here, in the test (§6.1: IST fixed UTC+05:30).
"""

from __future__ import annotations

import datetime as dt
from functools import cache

import numpy as np
import pandas as pd
import pvlib
import pytest

from pipeline import config
from shared.solar_numpy import solar_position, solar_position_truncated

# §9 Delhi test coordinates and the strict equivalence thresholds.
LAT_DEG, LON_DEG = 28.6, 77.19
ALT_TOL_DEG = 0.5
AZ_TOL_DEG = 0.5

# §6.1: IST is a fixed UTC+05:30 offset, no DST.
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UTC = dt.timezone.utc

# Slot 20 is 12:00 IST under the §6.2 grid (07:00 + 15·20 min).
NOON_SLOT = (12 * 60 - config.SLOT_START_MINUTES) // 15
NOON_SLOT_TOLERANCE = 2  # §9: peak-altitude slot within 2 slots of IST ~12:00


def _slot_datetimes_ist(date_iso: str) -> list[dt.datetime]:
    """The 48-slot grid for one season date (§6.2), as aware IST datetimes."""
    day = dt.date.fromisoformat(date_iso)
    first = dt.datetime(
        day.year,
        day.month,
        day.day,
        config.SLOT_START_MINUTES // 60,
        config.SLOT_START_MINUTES % 60,
        tzinfo=IST,
    )
    return [first + dt.timedelta(minutes=15 * i) for i in range(config.SLOTS)]


def _to_utc(times_ist: list[dt.datetime]) -> list[dt.datetime]:
    """IST → UTC conversion — part of the test's own duty (§6.1)."""
    return [t.astimezone(UTC) for t in times_ist]


def _azimuth_error_deg(actual, reference) -> np.ndarray:
    """Wrapped absolute angular difference in degrees (handles the 0/360 wrap)."""
    return np.abs(np.mod(reference - actual + 180.0, 360.0) - 180.0)


@cache
def _solar_grid(date_iso: str):
    """Solar position over one season grid, our module and pvlib, computed once."""
    utc_slots = _to_utc(_slot_datetimes_ist(date_iso))
    alt_np, az_np = solar_position(LAT_DEG, LON_DEG, utc_slots)

    sp = pvlib.solarposition.get_solarposition(
        pd.DatetimeIndex(utc_slots), LAT_DEG, LON_DEG, pressure=0.0
    )
    # pressure=0 -> zero atmospheric refraction: pvlib's 'zenith' column is the
    # geometric zenith, which is what §7.4 mandates comparing against.
    alt_pv = 90.0 - sp["zenith"].to_numpy()
    az_pv = sp["azimuth"].to_numpy()
    return alt_np, az_np, alt_pv, az_pv


@pytest.mark.parametrize("season", ["summer", "monsoon"])
def test_altitude_matches_pvlib_within_half_degree(season):
    alt_np, _, alt_pv, _ = _solar_grid(config.SEASON_DATES[season])
    worst = float(np.max(np.abs(alt_np - alt_pv)))
    assert worst < ALT_TOL_DEG, f"{season}: worst altitude error {worst:.4f} deg"


@pytest.mark.parametrize("season", ["summer", "monsoon"])
def test_azimuth_matches_pvlib_within_half_degree(season):
    _, az_np, _, az_pv = _solar_grid(config.SEASON_DATES[season])
    worst = float(np.max(_azimuth_error_deg(az_np, az_pv)))
    assert worst < AZ_TOL_DEG, f"{season}: worst azimuth error {worst:.4f} deg"


@pytest.mark.parametrize("season", ["summer", "monsoon"])
def test_peak_altitude_slot_is_solar_noon_within_two_slots(season):
    alt_np, _, _, _ = _solar_grid(config.SEASON_DATES[season])
    peak_slot = int(np.argmax(alt_np))
    drift = abs(peak_slot - NOON_SLOT)
    assert drift <= NOON_SLOT_TOLERANCE, (
        f"{season}: max-altitude slot {peak_slot} is {drift} slots from 12:00 IST"
    )


def test_altitude_is_negative_after_sunset_anchors():
    """§9: altitude at instants where the sun is below the horizon is negative.

    The 07:00–18:45 grid itself stays above the horizon on both season dates,
    so the §9 negative-altitude check extends the same equations to post-sunset
    anchors just outside the grid.
    """
    # (date, IST hour, minute): sun below horizon on 2026-05-15 / 2026-07-15.
    anchors = [
        ("2026-05-15", 19, 15),
        ("2026-05-15", 19, 30),
        ("2026-05-15", 20, 0),
        ("2026-07-15", 19, 30),
        ("2026-07-15", 20, 0),
    ]
    for date_iso, hour, minute in anchors:
        day = dt.date.fromisoformat(date_iso)
        ist = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)
        alt_deg, _ = solar_position(LAT_DEG, LON_DEG, ist.astimezone(UTC))
        assert alt_deg < 0.0, f"{ist.isoformat()} below horizon, got {alt_deg:+.3f} deg"


def test_azimuth_convention_morning_shadows_west_evening_east():
    """§7.5 azimuth direction — numerically encodes the human plot-review gate.

    Sun in the eastern sky in the morning implies shadows point west (az+180 in
    the W quadrant); sun WNW in the evening implies shadows point east.
    """
    date_iso = config.SEASON_DATES["summer"]
    _, az_np, _, _ = _solar_grid(date_iso)

    morning_az = az_np[16]  # slot 16 = 11:00 IST — sun in the E/SE sky
    shadow_dir_morning = (morning_az + 180.0) % 360.0
    assert 60.0 < morning_az < 120.0, "late-morning sun must sit in the E/SE sky"
    assert 240.0 < shadow_dir_morning < 300.0, "late-morning shadows must point W"

    evening_az = az_np[40]  # slot 40 = 17:00 IST — sun in the W/WNW sky
    shadow_dir_evening = (evening_az + 180.0) % 360.0
    assert 240.0 < evening_az < 300.0, "17:00 sun must sit in the W/WNW sky"
    assert 60.0 < shadow_dir_evening < 120.0, "evening shadows must point E"


def test_input_forms_agree_on_one_instant():
    """Scalar float out; aware/naive/list/array/datetime64 inputs all agree."""
    ist = dt.datetime(2026, 5, 15, 12, 0, tzinfo=IST)
    naive_utc = ist.astimezone(UTC).replace(tzinfo=None)
    np64 = np.datetime64(naive_utc, "us")

    alt_scalar, az_scalar = solar_position(LAT_DEG, LON_DEG, ist)
    assert isinstance(alt_scalar, float) and isinstance(az_scalar, float)

    alt_naive, _ = solar_position(LAT_DEG, LON_DEG, naive_utc)
    alt_list, _ = solar_position(LAT_DEG, LON_DEG, [ist])
    alt_arr, _ = solar_position(LAT_DEG, LON_DEG, np.array([ist], dtype=object))
    alt_64, az_64 = solar_position(LAT_DEG, LON_DEG, np64)

    assert alt_scalar == pytest.approx(alt_naive, abs=1e-9)
    assert alt_scalar == pytest.approx(alt_list, abs=1e-9)
    assert alt_scalar == pytest.approx(alt_arr, abs=1e-9)
    assert alt_scalar == pytest.approx(alt_64, abs=1e-9)
    assert az_scalar == pytest.approx(az_64, abs=1e-9)

    # Multi-slot input returns numpy arrays of the same length.
    utc_grid = _to_utc(_slot_datetimes_ist("2026-05-15"))
    alt_grid, az_grid = solar_position(LAT_DEG, LON_DEG, utc_grid)
    assert isinstance(alt_grid, np.ndarray) and alt_grid.shape == (config.SLOTS,)
    assert isinstance(az_grid, np.ndarray) and az_grid.shape == (config.SLOTS,)

    # Empty input returns empty arrays.
    alt_empty, az_empty = solar_position(LAT_DEG, LON_DEG, [])
    assert len(alt_empty) == 0 and len(az_empty) == 0

    # Out-of-range coordinates raise, not silently wrap.
    with pytest.raises(ValueError):
        solar_position(91.0, LON_DEG, ist)
    with pytest.raises(ValueError):
        solar_position(LAT_DEG, 190.0, ist)


def test_accurate_formulation_outruns_the_truncated_series():
    """DECISIONS.md: the accurate NOAA formulation exists to clear §9's 0.5°
    azimuth gate at near-zenith slots, where the truncated fractional-year
    series loses precision. The gate fails for the truncated ladder and passes
    for the accurate one — this locks that in.
    """
    date_iso = config.SEASON_DATES["summer"]
    utc_slots = _to_utc(_slot_datetimes_ist(date_iso))

    _, az_acc = solar_position(LAT_DEG, LON_DEG, utc_slots)
    _, az_trunc = solar_position_truncated(LAT_DEG, LON_DEG, utc_slots)
    sp = pvlib.solarposition.get_solarposition(
        pd.DatetimeIndex(utc_slots), LAT_DEG, LON_DEG, pressure=0.0
    )
    az_pv = sp["azimuth"].to_numpy()

    err_acc = float(np.max(_azimuth_error_deg(az_acc, az_pv)))
    err_trunc = float(np.max(_azimuth_error_deg(az_trunc, az_pv)))
    assert err_acc < err_trunc, "truncated series must not beat the accurate one"
    assert err_trunc >= 0.5, "truncated series must violate the §9 azimuth gate"
    assert err_acc < AZ_TOL_DEG
