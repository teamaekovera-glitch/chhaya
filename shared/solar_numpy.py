"""Pure-numpy NOAA solar-position module — CLAUDE.md §7.4 canonical implementation.

Import surface frozen for pipeline/shade.py and lambdas/shade_slot (§5 vendors this
file into the Lambda; only the numpy version may live inside a Lambda):

    from shared.solar_numpy import solar_position

    altitude_deg, azimuth_deg = solar_position(lat, lon, when_utc)

- ``lat`` / ``lon``: scalar degrees (WGS84).
- ``when_utc``: aware datetime (any UTC offset is converted), naive datetime
  (interpreted as UTC), or a list/tuple/np.ndarray of datetimes.
- Scalar in -> (float, float) out; sequence in -> (np.ndarray, np.ndarray) out.
- ``altitude_deg`` is in [-90, 90]; ``azimuth_deg`` is in [0, 360) counted
  CLOCKWISE FROM TRUE NORTH (0=N, 90=E, 180=S) — the §7.5 convention, where the
  shadow direction away from the sun is ``azimuth_deg + 180°``.
- Geometric position only: atmospheric refraction is NOT applied, so the §7.4
  pvlib acceptance check compares geometric against geometric (tests use pvlib's
  refraction-free ``zenith`` column).
- The §9 equivalence gate needs < 0.5° in azimuth *including the near-zenith
  slots*, where the truncated NOAA fractional-year series is weakest (its own
  published accuracy is around ±0.5°–1°, lost in azimuth as zenith -> 0 since
  dAz/dDec grows like 1/sin(zenith)). ``solar_position`` therefore implements
  the NOAA calculator's high-accuracy formulation (Julian-century time variable
  in the fractional-year role, Meeus-style apparent ecliptic longitude and
  obliquity -> declination and equation of time, then the same hour-angle /
  zenith / azimuth spherical trig); the truncated ladder of the same doc is
  kept as ``solar_position_truncated`` for traceability and is outrun by the
  accurate version in tests. Both share one contract surface.
- Low-sun handling (alt < 5° -> shade = 1.0) is a §7.5 caller concern, not this
  module's: the true geometric altitude is returned even below the horizon.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

__all__ = ["solar_position", "solar_position_truncated"]

_TUTC = dt.timezone.utc


# ---------------------------------------------------------------- input massaging
def _to_utc_naive(t: dt.datetime) -> dt.datetime:
    """Normalise one datetime to naive UTC (§6.1: IST inputs are converted by callers)."""
    if t.tzinfo is not None:
        return t.astimezone(_TUTC).replace(tzinfo=None)
    return t


def _iter_utc_datetimes(when_utc) -> list[dt.datetime]:
    """Accept a datetime or any iterable/array of them; return naive-UTC datetimes."""
    if isinstance(when_utc, dt.datetime):
        return [_to_utc_naive(when_utc)]

    if isinstance(when_utc, np.ndarray):
        if when_utc.dtype.kind == "M":  # np.datetime64 -> plain datetime (naive UTC)
            items = [v.item() for v in np.asarray(when_utc, dtype="datetime64[us]").tolist()]
        else:
            items = list(when_utc.ravel())
    elif isinstance(when_utc, np.datetime64):
        items = [np.datetime64(when_utc, "us").item()]
    elif isinstance(when_utc, (list, tuple)) or hasattr(when_utc, "__iter__"):
        items = [np.datetime64(v).item() if isinstance(v, np.datetime64) else v for v in when_utc]
    else:
        raise TypeError(
            "when_utc must be a datetime or an iterable of datetimes, "
            f"got {type(when_utc)!r}"
        )

    times: list[dt.datetime] = []
    for v in items:
        if not isinstance(v, dt.datetime):
            raise TypeError(f"when_utc entries must be datetime instances, got {type(v)!r}")
        times.append(_to_utc_naive(v))
    return times


def _julian_days(times: list[dt.datetime]) -> np.ndarray:
    """Meeus Julian Day (incl. fractional day) for naive-UTC datetimes.

    Vector core in numpy; the per-element branch is a small loop over the 48-slot
    grid, which is the only shape the pipeline feeds (§6.2).
    """
    jd = np.empty(len(times))
    for i, t in enumerate(times):
        y, m = t.year, t.month
        d = t.day + (t.hour + t.minute / 60.0 + (t.second + t.microsecond / 1e6) / 3600.0) / 24.0
        if m <= 2:
            y -= 1
            m += 12
        a = y // 100
        b = 2 - a + a // 4
        jd[i] = (
            np.floor(365.25 * (y + 4716))
            + np.floor(30.6001 * (m + 1))
            + d
            + b
            - 1524.5
        )
    return jd


# ------------------------------------------------------- accurate NOAA formulation
def _sun_coordinates(t: np.ndarray):
    """Apparent declination (deg) and equation of time (min), Meeus/J2000 chain."""
    # Julian centuries since J2000 — the accurate fractional-year term (§7.4).
    tc = (t - 2451545.0) / 36525.0

    # Geometric mean longitude (deg) and anomaly (deg), eccentricity of the orbit.
    l0_deg = (280.46646 + tc * (36000.76983 + 0.0003032 * tc)) % 360.0
    m_deg = 357.52911 + tc * (35999.05029 - 0.0001537 * tc)
    e = 0.016708634 - tc * (0.000042037 + 0.0000001267 * tc)

    # Sun's equation of the center -> true ecliptic longitude.
    m_rad = np.radians(m_deg)
    c_deg = (
        np.sin(m_rad) * (1.914602 - tc * (0.004817 + 0.000014 * tc))
        + np.sin(2.0 * m_rad) * (0.019993 - 0.000101 * tc)
        + np.sin(3.0 * m_rad) * 0.000289
    )
    true_long_deg = l0_deg + c_deg

    # Apparent longitude: nutation (mean ascending node Omega) + aberration.
    omega_deg = 125.04 - 1934.136 * tc
    lam_deg = true_long_deg - 0.00569 - 0.00478 * np.sin(np.radians(omega_deg))

    # Obliquity of the ecliptic, with the nutation-in-obliquity term.
    eps0_deg = 23.0 + (26.0 + (21.448 - tc * (46.8150 + tc * (0.00059 - tc * 0.001813))) / 60.0) / 60.0
    eps_deg = eps0_deg + 0.00256 * np.cos(np.radians(omega_deg))

    # Declination of the geometric center of the sun (deg).
    dec_deg = np.degrees(
        np.arcsin(np.sin(np.radians(eps_deg)) * np.sin(np.radians(lam_deg)))
    )

    # Equation of time (minutes): means the sundial fast/slow correction.
    y = np.tan(np.radians(eps_deg / 2.0)) ** 2
    eot_min = 4.0 * np.degrees(
        y * np.sin(2.0 * np.radians(l0_deg))
        - 2.0 * e * np.sin(m_rad)
        + 4.0 * e * y * np.sin(m_rad) * np.cos(2.0 * np.radians(l0_deg))
        - 0.5 * y * y * np.sin(4.0 * np.radians(l0_deg))
        - 1.25 * e * e * np.sin(2.0 * m_rad)
    )
    return dec_deg, eot_min


def _altitude_azimuth(lat_rad: float, dec_rad: np.ndarray, ha_rad: np.ndarray):
    """Zenith/altitude + azimuth (deg, clockwise from north) shared spherical trig."""
    cos_zenith = np.sin(lat_rad) * np.sin(dec_rad) + np.cos(lat_rad) * np.cos(
        dec_rad
    ) * np.cos(ha_rad)
    zenith = np.arccos(np.clip(cos_zenith, -1.0, 1.0))
    altitude_deg = 90.0 - np.degrees(zenith)

    # Azimuth from SOUTH, positive westward -> shift to clockwise-from-north.
    denom = np.cos(ha_rad) * np.sin(lat_rad) - np.tan(dec_rad) * np.cos(lat_rad)
    az_from_south = np.arctan2(np.sin(ha_rad), denom)
    azimuth_deg = (180.0 + np.degrees(az_from_south)) % 360.0
    return altitude_deg, azimuth_deg


def _positions_from_times(lat: float, lon: float, times: list[dt.datetime]):
    """Common body: JD -> solar coords -> hour angle -> altitude/azimuth arrays."""
    jd = _julian_days(times)
    dec_deg, eot_min = _sun_coordinates(jd)
    dec_rad = np.radians(dec_deg)
    lat_rad = np.radians(lat)

    hours = np.array(
        [
            t.hour + t.minute / 60.0 + (t.second + t.microsecond / 1e6) / 3600.0
            for t in times
        ]
    )
    # True solar time, minutes past local-solar midnight: UTC clock plus the
    # equation of time plus the 4*longitude min/deg meridian correction.
    tst_min = hours * 60.0 + eot_min + 4.0 * lon
    ha_rad = np.radians(tst_min / 4.0 - 180.0)  # hour angle in degrees / 4 == min/4

    return _altitude_azimuth(lat_rad, dec_rad, ha_rad)


def solar_position(lat, lon, when_utc):
    """Return (altitude_deg, azimuth_deg) of the true sun position.

    azimuth is clockwise from true north (§7.5 convention). Scalar datetimes
    in -> scalar floats out; array-like in -> (np.ndarray, np.ndarray).
    """
    lat = float(lat)
    lon = float(lon)
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude out of range [-90, 90]: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude out of range [-180, 180]: {lon}")

    times = _iter_utc_datetimes(when_utc)
    if not times:
        empty = np.array([], dtype=float)
        return (empty, empty.copy())

    altitude_deg, azimuth_deg = _positions_from_times(lat, lon, times)

    if len(times) == 1:
        return float(altitude_deg[0]), float(azimuth_deg[0])
    return altitude_deg, azimuth_deg


# -------------------------------------------------- truncated fractional-year ladder
_TWO_PI_OVER_365 = 2.0 * np.pi / 365.0  # NOAA fractional-year constant, radians/day


def _truncated_eot_min(gamma: np.ndarray) -> np.ndarray:
    """NOAA solar-calculator equation of time series, minutes, gamma in radians.

    Constant is the corrected Spencer value 0.0000075 (the printed 0.000075 is a
    documented erratum in the original paper's series).
    """
    return 229.18 * (
        0.0000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2.0 * gamma)
        - 0.040849 * np.sin(2.0 * gamma)
    )


def _truncated_declination_rad(gamma: np.ndarray) -> np.ndarray:
    """NOAA solar-calculator declination series, Spencer four-term truncation."""
    return (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2.0 * gamma)
        + 0.000907 * np.sin(2.0 * gamma)
        - 0.002697 * np.cos(3.0 * gamma)
        + 0.001480 * np.sin(3.0 * gamma)
    )


def solar_position_truncated(lat, lon, when_utc):
    """Same contract as :func:`solar_position` from the truncated NOAA series.

    Retained for §7.4 traceability and as the accuracy baseline the tests outrun;
    production code imports :func:`solar_position` only.
    """
    lat = float(lat)
    lon = float(lon)
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude out of range [-90, 90]: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude out of range [-180, 180]: {lon}")

    times = _iter_utc_datetimes(when_utc)
    if not times:
        empty = np.array([], dtype=float)
        return (empty, empty.copy())

    hours = np.array(
        [
            (t + dt.timedelta(hours=lon / 15.0)).hour
            + (t + dt.timedelta(hours=lon / 15.0)).minute / 60.0
            + (
                (t + dt.timedelta(hours=lon / 15.0)).second
                + (t + dt.timedelta(hours=lon / 15.0)).microsecond / 1e6
            )
            / 3600.0
            for t in times
        ]
    )
    doys = np.array(
        [(t + dt.timedelta(hours=lon / 15.0)).timetuple().tm_yday for t in times]
    )
    gamma = _TWO_PI_OVER_365 * (doys - 1.0 + (hours - 12.0) / 24.0)
    dec_rad = _truncated_declination_rad(gamma)
    eot_min = _truncated_eot_min(gamma)

    tst_min = hours * 60.0 + eot_min
    ha_rad = np.radians(0.25 * (tst_min - 720.0))
    altitude_deg, azimuth_deg = _altitude_azimuth(np.radians(lat), dec_rad, ha_rad)

    if len(times) == 1:
        return float(altitude_deg[0]), float(azimuth_deg[0])
    return altitude_deg, azimuth_deg
