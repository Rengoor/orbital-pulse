"""CUSUM drift detection per channel.

Owner: person A
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CUSUMState:
    """Holds the two running sums for Page's tabular CUSUM test.

    Invariant: s_pos >= 0 and s_neg <= 0 at all times.
    """
    s_pos: float  # upper cumulative sum (non-negative)
    s_neg: float  # lower cumulative sum (non-positive)


def cusum_update(
    state: CUSUMState,
    value: float,
    mean: float,
    std: float,
    k: float,
) -> CUSUMState:
    """Pure CUSUM update step (Page's test).

    Preconditions:
        std > 0
        k > 0
        state.s_pos >= 0
        state.s_neg <= 0

    Returns a NEW CUSUMState; never mutates *state*.

    Postconditions:
        new_state.s_pos >= 0
        new_state.s_neg <= 0
    """
    z = (value - mean) / std
    s_pos = max(0.0, state.s_pos + z - k)
    s_neg = min(0.0, state.s_neg + z + k)
    return CUSUMState(s_pos=s_pos, s_neg=s_neg)


def cusum_alarm(state: CUSUMState, h: float) -> bool:
    """Return True if either accumulator has exceeded the threshold *h*."""
    return (state.s_pos > h) or (state.s_neg < -h)


def run_cusum_series(
    values: list[float],
    mean: float,
    std: float,
    k: float,
    h: float,
) -> tuple[bool, list[CUSUMState]]:
    """Run CUSUM over an ordered series of values.

    Loop invariant: after each update, history[-1].s_pos >= 0
    and history[-1].s_neg <= 0.

    Returns:
        (alarm_triggered, state_history)
        where state_history[i] is the CUSUMState after processing values[i].
    """
    state = CUSUMState(s_pos=0.0, s_neg=0.0)
    history: list[CUSUMState] = []
    alarm = False

    for v in values:
        state = cusum_update(state, v, mean, std, k)
        history.append(state)
        if cusum_alarm(state, h):
            alarm = True

    return alarm, history
