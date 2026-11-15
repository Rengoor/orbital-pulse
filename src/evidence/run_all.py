"""One command, fixed seed: runs ablation, sensitivity, red team, rule-change replay and downlink efficiency; writes results/.

    python -m evidence.run_all [--seed 42]

Writes evidence/results/{ablation,sensitivity,rulechange_replay,
downlink_efficiency,autonomy}.{md,json} and redteam.{md,json}, then prints one
summary line per runner. Exit code 0 only when the red team reports zero
unsafe approvals.

Every table states its own caveats; the shared ones: the scenarios are
simulated drafts, the limits are project-defined placeholders (not NASA
medical limits), and timing numbers hold for this machine and run only.

Owner: person D
"""

from __future__ import annotations

import argparse
import json
import sys

from evidence import ablation, autonomy, downlink_efficiency, rulechange_replay, sensitivity
from evidence._harness import RESULTS, write_results
from evidence.redteam import run_redteam


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    summary: list[str] = []

    for name, module in (
        ("ablation", ablation),
        ("sensitivity", sensitivity),
        ("rulechange_replay", rulechange_replay),
        ("downlink_efficiency", downlink_efficiency),
        ("autonomy", autonomy),
    ):
        data = module.run(seed=args.seed)
        write_results(name, module.to_markdown(data), data)
        summary.append(f"{name}: wrote results/{name}.md and .json")

    redteam_results = run_redteam.run_all()
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "redteam.md").write_text(run_redteam.to_markdown(redteam_results), encoding="utf-8", newline="\n")
    (RESULTS / "redteam.json").write_text(json.dumps(redteam_results, indent=2) + "\n", encoding="utf-8", newline="\n")
    unsafe = sum(not r["blocked"] for r in redteam_results)
    summary.append(
        f"redteam: {len(redteam_results)} attacks, {len(redteam_results) - unsafe} blocked, "
        f"{unsafe} unsafe approvals"
    )

    print(f"seed {args.seed}")
    for line in summary:
        print(line)
    return 1 if unsafe else 0


if __name__ == "__main__":
    sys.exit(main())
