"""The evidence runners produce real, reproducible numbers with their caveats attached."""

from __future__ import annotations

import os

import pytest

from evidence import ablation, downlink_efficiency, rulechange_replay, sensitivity
from evidence._harness import pure_data_attacks

os.environ.setdefault("SIGNING_KEY", "evidence-test-signing-key")


@pytest.fixture(scope="module")
def ablation_data():
    return ablation.run(seed=42)


def test_ablation_full_system_blocks_every_pure_data_attack(ablation_data):
    full = ablation_data["conditions"]["full"]
    assert full["unsafe_approvals"] == 0
    assert full["false_alarms_per_day"] == 0
    assert full["detection_delay_events"] == 0  # flags at the first limit breach


def test_ablation_shows_what_each_layer_adds(ablation_data):
    conditions = ablation_data["conditions"]
    # Without the gate and Checker, pure-data attacks get through somewhere.
    for name in ("a_only", "b_only", "a_plus_b", "fixed_threshold"):
        assert conditions[name]["unsafe_approvals"] > 0, name
    # And no ablated condition beats the full system.
    floor = conditions["full"]["unsafe_approvals"]
    assert all(c["unsafe_approvals"] >= floor for c in conditions.values())


def test_ablation_is_deterministic(ablation_data):
    again = ablation.run(seed=42)
    assert again == ablation_data


def test_ablation_markdown_carries_the_caveats(ablation_data):
    md = ablation.to_markdown(ablation_data)
    assert "project-defined placeholders" in md
    assert "simulated drafts" in md


def test_sensitivity_integrity_verdicts_do_not_move_with_thresholds():
    data = sensitivity.run(seed=42)
    # Attacks about data integrity (not about where a value sits against a
    # bound) must be GREY at every factor: the gate, not the table, caught them.
    integrity_cases = {"stale_data", "stuck_sensor", "unit_mismatch",
                       "contradictory_sensors", "fake_nasa_provenance", "empty_checkin"}
    seen = set()
    for row in data["factors"]:
        for attack in row["attacks"]:
            if attack["id"] in integrity_cases:
                seen.add(attack["id"])
                assert attack["observed"] == "GREY", (row["factor"], attack["id"])
    assert seen == integrity_cases
    # The baseline factor reproduces the shipped table: nothing unsafe at x1.0.
    baseline = next(r for r in data["factors"] if r["factor"] == 1.0)
    assert baseline["unsafe_approvals"] == 0
    assert baseline["normal_false_alarms"] == 0


def test_rulechange_replay_flags_only_the_loosening_as_unsafe():
    data = rulechange_replay.run(seed=42)
    proposals = data["proposals"]
    assert proposals["tighten_dose"]["unsafe"] == 0
    assert proposals["tighten_sleep"]["unsafe"] == 0
    assert proposals["loosen_dose"]["unsafe"] >= 1  # the reviewer must see these rows
    assert all(p["total"] == data["records"] for p in proposals.values())


def test_downlink_summaries_cost_less_and_hold_only_green():
    data = downlink_efficiency.run(seed=42)
    for link in data["links"]:
        assert link["summary_and_anchor_bytes"] < link["full_record_bytes"]
        if link["one_way_delay_s"] <= 60:
            assert link["held_for_digest"] == 0  # short link: nothing waits
        else:
            # long link: only routine GREEN traffic waits for the digest
            assert link["sent_immediately"] + link["held_for_digest"] == data["records"]
    timing = data["checkin_timing"]
    assert timing["events"] > 0 and timing["median_s"] > 0


def test_pure_data_attack_set_is_the_expected_subset():
    ids = {a["id"] for a in pure_data_attacks()}
    # No LLM-stub, pipeline-kill or policy-swap cases: those attack machinery
    # the ablated conditions do not have, so feeding them would be unfair.
    assert "llm_suggests_dose" not in ids
    assert "pipeline_a_killed" not in ids
    assert {"stale_data", "stuck_sensor", "implausible_jump", "empty_checkin"} <= ids
