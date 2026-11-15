# data/

**Owner:** person D

The contract (schemas), real NASA data ingestion, the daily-vitals simulator, scenarios and fixtures. Plain files plus small scripts.

## Rules for this folder

- `schemas/` is the contract. Frozen in hour one, then additive changes only.
- Real: Inspiration4 baselines (OSDR), RadLab dose rates, DONKI event window. Simulated, and labelled everywhere: daily vitals and crew locations.
- Time-box each NASA pull to 45 minutes; fallbacks are listed in `nasa/README.md`.
- Raw downloads go to `nasa/raw/` (git-ignored). Commit only small processed files.
- Blind scenarios must be written by someone who has not seen pipelines A and B.
- Fixed seed everywhere (`SEED`).
