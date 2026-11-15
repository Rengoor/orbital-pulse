# evidence/

Everything judges can check. One command regenerates every table, so reported numbers come only from runs of the committed code.

```bash
backend/.venv/bin/python -m evidence.run_all --seed 42     # writes every table in results/
backend/.venv/bin/python -m evidence.redteam.run_redteam   # exit 1 if any attack gets an unsafe approval
```

| Path | What it holds |
|---|---|
| `run_all.py` | Runs every runner below with one seed |
| `ablation.py` → `results/ablation.md` | Full system vs stripped-down variants (no Checker, no input gate, single pipeline, …): unsafe approvals per variant |
| `sensitivity.py` → `results/sensitivity.md` | What happens to the verdicts when every placeholder limit is scaled |
| `autonomy.py` → `results/autonomy.md` | Who can decide (ground or crew) per alert at each distance from Earth |
| `downlink_efficiency.py` → `results/downlink_efficiency.md` | Bytes for the prioritised digest vs sending everything |
| `rulechange_replay.py` → `results/rulechange_replay.md` | A proposed rule change replayed against all past decisions before uplink |
| `redteam/` | 18 attack cases, one JSON file each, run against the real backend → `results/redteam.md` |
| `docs/` | `ai_declaration.md`, `hazard_coverage.md`, `limits.md`, `sources.md` |
| `usability/` | The formative usability protocol and its raw results |
| `tests/` | Checks that every runner still produces its table |

## Rules for this folder

- Imports `backend/`; never edits it.
- Red-team goal: zero unsafe approvals. CI fails otherwise.
- Report only results you ran. The usability test is formative and labelled so.
