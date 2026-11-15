# data/

The contract (schemas), real NASA data ingestion, the daily-vitals simulator, scenarios and fixtures. Plain files plus small scripts.

| Path | What it holds |
|---|---|
| `schemas/` | JSON Schemas for every object that crosses a boundary: reading, proposal, verdict, card, record, review, ack, handoff |
| `nasa/` | Fetch and reduce scripts for OSDR Inspiration4, OSDR RadLab and CCMC DONKI, with the small processed files committed under `*/processed/`. See `nasa/README.md` |
| `sim/` | The crew simulator (`simulator.py`, `crew.yaml`, `config.yaml`): simulated daily vitals, labelled simulated everywhere |
| `scenarios/` | Scenario days the simulator and evidence runners play: `normal_day.json`, `storm_day.json` |
| `fixtures/` | One valid example of each schema object |
| `tests/` | Schema and fixture tests |

## Rules for this folder

- `schemas/` is the contract. Additive changes only.
- Real: Inspiration4 baselines (OSDR), RadLab dose rates, DONKI event window. Simulated, and labelled everywhere: daily vitals and crew locations.
- Raw downloads go to `nasa/raw/` (git-ignored). Commit only small processed files.
- Fixed seed everywhere (`SEED`).
