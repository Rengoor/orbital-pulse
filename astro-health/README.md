# [Project name]

*An astronaut health tool that can never talk itself into reassuring you.*
Decision support, not diagnosis. NASA Space Apps Challenge 2026, Heilbronn: Create Health Monitoring Software for Astronauts on Space Missions.

## Criterion to evidence

| Criterion | Evidence | Where | Done |
|---|---|---|---|
| Relevance | Provenance on every decision card; baselines from real Inspiration4 draws; RadLab dose rates; DONKI event window | `data/nasa/`, `evidence/docs/hazard_coverage.md` | ☐ |
| Validity | End-to-end path; ablation table; red-team suite (10+ cases); threshold sensitivity; failure modes | `evidence/results/`, `evidence/redteam/` | ☐ |
| Creativity | Referee + flight recorder + Earth rule-change replay; lanes view; tamper test | `backend/checker/`, `backend/earth/`, `frontend/pages/` | ☐ |
| Impact | Downlink digest vs send-everything; check-in time; alerts per day; NASA's stated need for autonomy with post hoc confirmation | `evidence/results/`, `evidence/docs/sources.md` | ☐ |
| Presentation | One continuous Storm Day story across 7 slides; backup recording | `evidence/docs/slides_outline.md`, `evidence/docs/demo_script.md` | ☐ |

## Which output depends on which dataset

TODO (remove the data and that output must disappear).

## Layout

| Folder | What it holds |
|---|---|
| `backend/` | Pipelines, Checker, signed records, downlink queue, Earth verifier and replay, API |
| `frontend/` | Streamlit app: Gather, Evaluate, Act, lanes view, Storm Day, Earth console, time machine, tamper test |
| `data/` | Schemas (the contract), real NASA ingestion, simulator, scenarios, fixtures |
| `evidence/` | One-command reproducible results, red-team suite, usability notes, docs and slides |

## Run

```
make setup-backend setup-frontend setup-data setup-evidence
make api        # backend on :8000
make ui         # frontend (set MOCK_MODE=1 to run without the backend)
make reproduce  # fixed seed, regenerates every table in evidence/results/
```

## AI-use declaration

See `evidence/docs/ai_declaration.md` (fill in before submission).

## Limits

See `evidence/docs/limits.md`.
