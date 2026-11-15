"""run(readings, context) -> Proposal. Blind to every other pipeline.

Owner: person A
"""
from __future__ import annotations

from pathlib import Path

from backend.common.schema_check import validate
from backend.pipelines.a_statistical.cusum import CUSUMState, run_cusum_series
from backend.pipelines.a_statistical.patterns import evaluate_patterns

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIPELINE_ID = "a_statistical"

TIER_ORDER = {"GREEN": 0, "YELLOW": 1, "RED": 2, "GREY": 3}
TIER_BY_ORDER = {v: k for k, v in TIER_ORDER.items()}

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "data" / "schemas" / "proposal.schema.json"
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(readings: list[dict], context: dict) -> dict:
    """Compose baseline + CUSUM + patterns into one validated Proposal.

    Parameters
    ----------
    readings:
        List of reading dicts validated against reading.schema.json.
    context:
        Dict with keys:
          - ``baselines``: ``{channel: BaselineStats}``
          - ``rules``: ``{"cusum": {"k": float, "h": float}, "patterns": list}``
          - ``now``: datetime

    Returns
    -------
    dict
        A Proposal dict validated against proposal.schema.json with
        ``pipeline_id="a_statistical"``.
    """
    baselines: dict = context.get("baselines", {})
    rules: dict = context.get("rules", {})

    cusum_params: dict = rules.get("cusum", {"k": 0.5, "h": 4.0})
    k: float = float(cusum_params.get("k", 0.5))
    h: float = float(cusum_params.get("h", 4.0))

    pattern_rules: list = rules.get("patterns", [])

    # ------------------------------------------------------------------
    # Step 1: Run CUSUM per channel
    # ------------------------------------------------------------------
    # Group reading values per channel (in encounter order = time order)
    channel_readings: dict[str, list[dict]] = {}
    for reading in readings:
        ch = reading.get("channel")
        if ch is not None:
            channel_readings.setdefault(ch, []).append(reading)

    tier = "GREEN"
    reasons: list[str] = []
    reading_ids: list[str] = []

    for channel, ch_readings in channel_readings.items():
        baseline = baselines.get(channel)
        if baseline is None:
            # No baseline for this channel — skip CUSUM
            continue

        values = [float(r["value"]) for r in ch_readings]
        alarm, _ = run_cusum_series(
            values=values,
            mean=baseline.mean,
            std=baseline.std,
            k=k,
            h=h,
        )

        if alarm:
            # CUSUM alarm → at least YELLOW
            if TIER_ORDER[tier] < TIER_ORDER["YELLOW"]:
                tier = "YELLOW"
            reasons.append(f"CUSUM alarm on channel {channel!r}")
            # Collect all reading IDs for this channel as contributors
            for r in ch_readings:
                rid = r.get("id")
                if rid and rid not in reading_ids:
                    reading_ids.append(rid)

    # ------------------------------------------------------------------
    # Step 2: Evaluate patterns
    # ------------------------------------------------------------------
    pattern_matches = evaluate_patterns(readings, baselines, pattern_rules)
    rule_ids: list[str] = []

    for match in pattern_matches:
        if not match.matched:
            continue
        # Pattern fired — merge its tier
        if TIER_ORDER[match.tier] > TIER_ORDER[tier]:
            tier = match.tier
        reasons.extend(match.reasons)
        if match.rule_id and match.rule_id not in rule_ids:
            rule_ids.append(match.rule_id)
        # Collect reading IDs for channels referenced in matched conditions
        # (use all readings as contributors when a pattern fires)
        for r in readings:
            rid = r.get("id")
            if rid and rid not in reading_ids:
                reading_ids.append(rid)

    # ------------------------------------------------------------------
    # Step 3: Build the Proposal
    # ------------------------------------------------------------------
    proposal: dict = {
        "pipeline_id": PIPELINE_ID,
        "tier": tier,
        "reasons": reasons,
        "data_fault": False,
        "reading_ids": reading_ids,
        "rule_ids": rule_ids,
    }

    # ------------------------------------------------------------------
    # Step 4: Validate against proposal.schema.json
    # ------------------------------------------------------------------
    validate(proposal, str(_SCHEMA_PATH))

    return proposal
