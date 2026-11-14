"""Delay model: about 1.3 s near the Moon up to 4-22 min one way at Mars.

Owner: person B
"""

from __future__ import annotations

SPEED_OF_LIGHT_KM_S = 299_792.458

# Representative Earth distances in km. Mars swings between closest approach
# and the far side of the Sun, which is where the 4-22 minute range comes from.
DISTANCES_KM = {
    "leo": 400.0,
    "moon": 384_400.0,
    "mars_near": 54_600_000.0,
    "mars_far": 401_000_000.0,
}


def one_way_delay_s(distance_km: float) -> float:
    """Light-travel time in seconds over *distance_km*."""
    if distance_km < 0:
        raise ValueError("distance_km must be non-negative")
    return distance_km / SPEED_OF_LIGHT_KM_S


def delay_for(location: str) -> float:
    """One-way delay in seconds for a named location (see DISTANCES_KM)."""
    try:
        return one_way_delay_s(DISTANCES_KM[location])
    except KeyError:
        raise ValueError(f"unknown location {location!r}; expected one of {sorted(DISTANCES_KM)}") from None


def round_trip_delay_s(distance_km: float) -> float:
    """Shortest possible time to get an answer back from the ground."""
    return 2 * one_way_delay_s(distance_km)
