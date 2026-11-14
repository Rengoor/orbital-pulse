# Limits (state openly)

Current as of 2026-11-14.

- **Daily vitals are simulated.** Only the glucose baselines, the blood-panel
  table, the radiation context and the demo event window use real NASA data,
  and every value in the UI carries a REAL or SIMULATED label.
- **Inspiration4 is four people on a three-day flight.** The replay is
  retrospective and does not show in-flight detection. Three pre-flight draws
  is a small baseline; pipeline A treats it as low confidence.
- **The simulator is our own**, so comparisons against it are indicative, not
  proof.
- **Every decision threshold is a project-defined placeholder** (see
  `backend/pipelines/b_limits/limits_table.yaml`: `basis: project_defined`,
  `source: PLACEHOLDER`). None has been sourced from a NASA document or
  reviewed by a clinician, and the UI says so on every card. Mood has no
  limit at all; pipeline A has no multi-channel patterns configured.
- **The sensitivity table quantifies the cost:** at limits x1.2 two red-team
  cases that should read RED read YELLOW (`evidence/results/sensitivity.md`).
  Integrity verdicts (GREY on stale, stuck or contradictory data) do not move
  with the thresholds.
- **The on-board LLM has only been tested with canned replies**, never a real
  local model. It stays disabled (`LLM_ENABLED` unset) until that test is run.
- **RadLab values are absorbed dose with an inferred unit** (uGy/h, not
  confirmed against RadLab documentation), so they are context only and never
  fed to the decision pipelines (`data/nasa/README.md`).
- **Earth reviewer verdicts are simulated** (`"simulated": true` in every
  review); no flight surgeon is in the loop.
- **Signing is one shared HMAC key**: records are tamper-evident only against
  someone who does not hold the key. Asymmetric signatures are the stated
  next step.
- **The API has no authentication or roles**; anyone who can reach it can
  read all records. It binds to loopback by default.
- **Decision support, not diagnosis.** Not through NASA software
  classification, crew testing, or validation on flight data. The HUD's
  README cites NASA-STD-3001 Volume 2 per display rule and lists what is
  *not* met; it does not claim compliance.
- **The blind scenarios are still unwritten** (`data/scenarios/blind_01.json`,
  `blind_02.json`): they are reserved for an author who has not seen the
  pipelines.
