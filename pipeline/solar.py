#!/usr/bin/env python3
"""CHHAYA solar position - thin pipeline wrapper (§7.4).

The canonical pure-numpy NOAA implementation lives in `shared/solar_numpy.py`
(owned by the parallel tests worker; the shade Lambda vendors the same file).
This module never forks the math: it imports the shared module, and exposes a
pvlib path for the pytest equivalence gate (tests/test_solar.py: max abs error
< 0.5 deg in altitude and azimuth against pvlib.solarposition.get_solarposition
for both season dates x 48 slots).

Contract (consumed by pipeline/shade.py):
    sun_position(times_ist, lon, lat) -> (altitude_deg, azimuth_deg)
    - times_ist: array-like of tz-aware datetimes (ZoneInfo "Asia/Kolkata")
    - azimuth is FROM NORTH, clockwise in degrees (§7.5)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _to_utc_index(times_ist) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(list(times_ist)))
    if idx.tz is None:
        idx = idx.tz_localize(IST)
    return idx.tz_convert(UTC)


def solar_position(times_ist, lon: float, lat: float) -> tuple[np.ndarray, np.ndarray]:
    """Altitude (deg, 0..90) and azimuth (deg, 0..360 from north, clockwise) per time."""
    from shared.solar_numpy import solar_position  # tests-worker-owned canonical port

    # Shared canon signature is (lat, lon, when_utc); it accepts array-like times.
    alt, az = solar_position(lat, lon, _to_utc_index(times_ist))
    return np.asarray(alt, dtype=float), np.asarray(az, dtype=float)


def pvlib_position(times_ist, lon: float, lat: float) -> tuple[np.ndarray, np.ndarray]:
    """pvlib reference implementation - used only by the equivalence test (§7.4)."""
    import pvlib

    idx = _to_utc_index(times_ist)
    sol = pvlib.solarposition.get_solarposition(idx, latitude=lat, longitude=lon)
    return sol["apparent_elevation"].to_numpy(), sol["azimuth"].to_numpy()


def season_slot_times(season: str, slot: int) -> datetime:
    """IST datetime for (season, slot) from config's grids - one place, not 3."""
    from config import SEASON_DATES, SLOT_START_MINUTES

    minutes = SLOT_START_MINUTES + 15 * slot
    hh, mm = divmod(minutes, 60)
    d = pd.Timestamp(SEASON_DATES[season]).date()
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST)


def season_slot_grid(season: str) -> list[datetime]:
    """All 48 slot datetimes for a season (§6.2)."""
    from config import SLOTS

    return [season_slot_times(season, s) for s in range(SLOTS)]
