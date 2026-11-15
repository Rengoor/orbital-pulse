# AstroHealth

*An astronaut health tool that can never talk itself into reassuring you.*

NASA Space Apps Challenge 2026 — **Create Health Monitoring Software for Astronauts on Space Missions**. All code lives under [`astro-health/`](astro-health/).

AstroHealth is decision support, not diagnosis. Our focus is the part most health monitors skip: **why should an astronaut trust what the screen says?** On a Mars mission the crew cannot phone a flight surgeon in time, so the software's word has to be worth something on its own. AstroHealth earns that trust with reliability and governance — independent assessments, a deterministic referee, tamper-evident records, and honest labels on every number — instead of asking the crew to take a model's word for it.

## Quick start

One command starts the backend, the crew simulator and all three views in your browser (Ctrl+C stops everything):

```bash
cd astro-health
./start.command            # macOS/Linux (double-click works too) · Windows: start.bat
```

Or step by step:

```bash
cd astro-health
python -m venv backend/.venv
backend/.venv/bin/python -m pip install -r evidence/requirements.txt
export SIGNING_KEY=local-dev-signing-key          # the API refuses to start without one
backend/.venv/bin/python run_demo.py              # backend + simulator + browser views
```

Windows PowerShell: use `backend\.venv\Scripts\python` and `$env:SIGNING_KEY = "local-dev-signing-key"`.

The UI is served by the backend at **http://127.0.0.1:8000/ui/**. `run_demo.py --storm` plays a radiation-storm day; `--link mars_far` shows what a 22-minute light delay does to who can decide. Tests: `backend/.venv/bin/python -m pytest backend/tests data/tests evidence/tests validation/tests -q`. Every evidence table regenerates with `backend/.venv/bin/python -m evidence.run_all --seed 42`.

## The interface: a HUD and two consoles

The frontend ([`astro-health/frontend/`](astro-health/frontend/)) is plain HTML/JS served by the backend, split by who is looking and how much attention they can spare. **Views display; they never decide.** No tier, threshold or medical rule exists in any frontend file — every verdict on screen is read from the backend, and a view with no backend link shows an explicit NO LINK state rather than stale or sample data.

| View | Who it is for | What it shows |
|---|---|---|
| [`hud/`](astro-health/frontend/hud/) — **Helmet HUD** | An astronaut on EVA, glanceable, camera-first with point-and-pinch control | Their own tier, the one authorized action, a disagreement marker, up to four vitals. Display rules cite NASA-STD-3001 Vol. 2 per rule in [`hud/README.md`](astro-health/frontend/hud/README.md) — including what is *not* met |
| [`tablet/monitor.html`](astro-health/frontend/tablet/monitor.html) — **Crew health monitor** | A crew member sitting down with time to read | Every monitored channel, the current verdict, and a "Why should I trust this decision?" panel that spells out which assessments agreed, what data was usable, and what is simulated |
| [`earth/`](astro-health/frontend/earth/) — **Earth base** | Ground oversight (read-only) | The full decision log, chain integrity and checkpoints, downlink queue, reviews, replay, rule-change testing, and the real NASA context data |

Every reading is labelled **REAL** (with its NASA dataset) or **SIMULATED** — the UI never lets one pass for the other.

## The pipeline: blind assessments, one referee

```
check-in ──► input gate ──► pipeline A (statistical)──┐
             (is the data    pipeline B (hard limits)──┼──► Checker ──► signed Record ──► views
              usable at      pipeline D (local LLM,  ──┘   (referee)      (hash-chained)
              all?)           optional, advisory)
```

- **Input gate** ([`backend/checker/input_gate.py`](astro-health/backend/checker/input_gate.py)): rejects stale, contradictory, mis-unit'd, stuck-sensor or fault-flagged readings before anything interprets them.
- **Pipeline A** ([`backend/pipelines/a_statistical/`](astro-health/backend/pipelines/a_statistical/)): per-astronaut baselines (built from real Inspiration4 blood draws) and CUSUM drift detection.
- **Pipeline B** ([`backend/pipelines/b_limits/`](astro-health/backend/pipelines/b_limits/)): an absolute limits table. Every row carries its `basis` and `source`; placeholders are declared as placeholders, and the UI says "project-defined limit", never "NASA medical limit".
- **Pipeline D** ([`backend/pipelines/d_llm/`](astro-health/backend/pipelines/d_llm/)): an optional local LLM (Ollama on loopback only). Strictly advisory — it can raise a tier, never lower one, never name a dose or drug, and a grounding check rejects any claim about data it was not given.
- The pipelines run **blind**: each gets its own copy of the readings and never sees another's output, so they cannot talk each other into agreement.
- **Checker** ([`backend/checker/`](astro-health/backend/checker/)): a small deterministic referee driven by a versioned, hashed policy file. It takes the most cautious proposal, escalates freely, and can lower a tier only through one path — every pipeline confirming a data fault, in which case the faulty reading is dropped and everything is re-assessed. Verdicts map to one of six whitelisted actions; tiers are GREEN / YELLOW / RED / **GREY** (the data cannot be verified — treated as urgent, never as "probably fine").
- **decide()** ([`backend/orchestrator.py`](astro-health/backend/orchestrator.py)) is pure: same inputs, same record, same hash. If any stage fails, a hard-coded fail-safe still issues a signed GREY / contact-ground record — the system never silently leaves the last good verdict on screen.

## The governance layer — what makes this different

Most monitoring projects stop at "model detects anomaly, screen turns red". AstroHealth is built around a different question: **what does it take for a crew to act on software's word, a 22-minute light-delay from any human expert?** Our answer is governance you can check, not accuracy you must believe:

- **Tamper-evident flight recorder.** Every decision is a hash-chained, HMAC-signed Record. Edit one and verification breaks at that record; delete recent history and the signed checkpoints catch the truncation.
- **Earth can verify and replay.** Ground re-runs any decision byte-for-byte from the record (same hash), files signed reviews in their own chain, and can test a proposed rule change against all past decisions *before* uplinking it — the replay flags any decision the new rules would have softened.
- **Delay-aware autonomy.** For every verdict the backend logs whether Earth's answer could arrive before the action deadline (`GROUND_IN_LOOP`) or the crew must act alone (`ONBOARD_AUTHORITY`). On our scenario days the crew owns 0 of 3 alerts alone near the Moon, but 3 of 3 at Mars's far point — the exact gap this system exists for.
- **Honesty is enforced, not promised.** GREY exists so that "I don't know" can never be dressed up as "all clear". Acknowledgements (who saw which verdict) live in their own signed chain. The LLM is caged: advisory, escalate-only, local, grounded.
- **Adversarially tested, reproducibly.** A red-team suite of 18 attacks (stale data, stuck sensors, forged NASA provenance, an LLM that suggests a dose, a killed pipeline, tampered and truncated history...) runs against the real backend: **18/18 blocked**. An ablation study shows the architecture earning its keep — the full system has 0 unsafe approvals where every stripped-down variant leaks 4–10. Threshold sensitivity, rule-change replay and downlink efficiency are all one command: `python -m evidence.run_all --seed 42`, results in [`evidence/results/`](astro-health/evidence/results/).
- **Validated against real NASA measurements.** [`validation/`](astro-health/validation/) runs real ISS dose-equivalent data (RadLab/ALTEA), real DONKI events and real Inspiration4 glucose through the unmodified decision system and reports what happens — including what the placeholder limits get wrong.

## NASA data

| Dataset | Role |
|---|---|
| OSDR Inspiration4 (OSD-569, OSD-575) | Personal glucose baselines for pipeline A; blood-panel tables; real post-flight glucose in the simulator |
| OSDR RadLab (DosTel, CRaTER, BPD, MSL-RAD; ALTEA for validation) | Radiation context in the views; real dose-equivalent validation runs |
| CCMC DONKI | Space-weather event timeline for the May 2024 storm window |

Remove a dataset and its output disappears — nothing substitutes fake data for it (dependency table in [`astro-health/README.md`](astro-health/README.md)).

## AI-use declaration

AI tools (Claude by Anthropic, via Claude Code) were used to help write code, tests and documentation in this repository. AI-assisted commits are marked with `Co-Authored-By: Claude ...` trailers in the git history, which is the authoritative metadata record. The team reviewed and ran all code; every reported number comes from real runs by the team or CI. Full declaration: [`astro-health/evidence/docs/ai_declaration.md`](astro-health/evidence/docs/ai_declaration.md). No NASA logos, flags or mission identifiers are used or modified anywhere in this project, and it contains no AI-generated images.

## Honest limits

Thresholds are project-defined placeholders awaiting medical review; the onboard LLM has not yet been tested against a real local model; signing uses one shared HMAC key; the API has no authentication yet. The full, current list is kept at [`astro-health/evidence/docs/limits.md`](astro-health/evidence/docs/limits.md) — stating these openly is part of the design.
