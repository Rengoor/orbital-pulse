# evidence/

**Owner:** person D (runners, red team, results) and person C (docs, usability, slides)

Everything judges check. One command regenerates every table, so reported numbers come only from runs by the team.

## Rules for this folder

- `python -m evidence.run_all --seed 42` writes all tables to `results/`.
- Imports `backend/`; never edits it.
- Red-team cases: one JSON file each in `redteam/cases/`. Goal: zero unsafe approvals.
- Report only results you ran. Label the usability test formative.
- `docs/` holds the Step 1 checklist, AI-use declaration, hazard coverage, limits, sources, demo script and slide outline.
