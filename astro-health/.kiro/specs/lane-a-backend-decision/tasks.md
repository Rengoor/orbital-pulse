# Tasks: Lane A — Backend Decision

## Task List

- [x] A-01: Stub `decide()` in `backend/orchestrator.py`
  - [x] A-01.1: Return `data/fixtures/sample_record.json` stamped with caller's `astronaut_id` and `now`
  - [x] A-01.2: Validate the fixture passes `record.schema.json` before returning
  - [x] A-01.3: Confirm `/checkin` returns HTTP 200 with a schema-valid Record (unblocks Lanes B and C)

- [x] A-02: Implement auto-discovery in `backend/pipelines/__init__.py`
  - [x] A-02.1: Use `pkgutil.iter_modules` to find subpackages with a `pipeline.py` exposing `run`
  - [x] A-02.2: Respect `LLM_ENABLED` env var — skip `d_llm` when `LLM_ENABLED != "1"`
  - [x] A-02.3: Log a warning (not an error) on `ImportError` for a subpackage and continue discovery
  - [x] A-02.4: Return deterministic list for a given filesystem state and env

- [x] A-03: Implement `backend/pipelines/a_statistical/baseline.py`
  - [x] A-03.1: Implement `BaselineStats` dataclass with `mean`, `std`, `n`, `low`, `high`, `confidence`
  - [x] A-03.2: Implement `compute_baseline(draws)` — sample std, `POPULATION_FALLBACK_STD` when `n < 2`
  - [x] A-03.3: Apply confidence multipliers: 2.0 (n≥10 → "high"), 3.0 (n≥4 → "medium"), 4.0 (n<4 → "low")
  - [x] A-03.4: Implement `load_baselines(astronaut_id, draws_path)` returning `{channel: BaselineStats}`
  - [x] A-03.5: Assert `stats.low <= stats.mean <= stats.high` for all outputs

- [x] A-04: Implement `backend/pipelines/a_statistical/cusum.py` and set parameters in `config.yaml`
  - [x] A-04.1: Implement `CUSUMState` dataclass with `s_pos` and `s_neg`
  - [x] A-04.2: Implement pure `cusum_update(state, value, mean, std, k)` — returns new state, never mutates input
  - [x] A-04.3: Implement `cusum_alarm(state, h)` returning bool
  - [x] A-04.4: Implement `run_cusum_series(values, mean, std, k, h)` returning `(alarm_triggered, state_history)`
  - [x] A-04.5: Set `config.yaml` to `cusum: {k: 0.5, h: 4.0}` (replace nulls)
  - [x] A-04.6: Confirm loop invariant: `s_pos >= 0` and `s_neg <= 0` after every update

- [x] A-05: Implement `backend/pipelines/a_statistical/patterns.py`
  - [x] A-05.1: Implement `PatternMatch` dataclass with `rule_id`, `matched`, `reasons`, `tier`
  - [x] A-05.2: Implement `evaluate_patterns(readings, baselines, rules)` — a pattern fires when ALL channel conditions are satisfied
  - [x] A-05.3: Support condition operators: `lt`, `gt`, `lte`, `gte`, `eq`
  - [x] A-05.4: Load pattern rules from `config.yaml::patterns`; return empty list when patterns list is empty

- [x] A-06: Implement `backend/pipelines/a_statistical/pipeline.py`
  - [x] A-06.1: Implement `run(readings, context)` composing baseline + CUSUM + patterns into one Proposal
  - [x] A-06.2: Merge results using worst-of tier across all channels and fired patterns
  - [x] A-06.3: Populate `reading_ids` and `rule_ids` on the returned Proposal
  - [x] A-06.4: Validate output against `proposal.schema.json` before returning
  - [x] A-06.5: Set `pipeline_id = "a_statistical"` on every output

- [x] A-07: Implement `backend/checker/gates.py`
  - [x] A-07.1: Implement `gate_worst_of(proposals)` — returns `max(tier)` using `GREEN=0,YELLOW=1,RED=2,GREY=3`
  - [x] A-07.2: Implement `gate_data_fault(proposals, current_tier)` — lower by one step only when ALL proposals have `data_fault=True`; never below GREEN
  - [x] A-07.3: Implement `gate_whitelist(action, policy_actions)` — escalate to next-higher whitelisted action if chosen action is absent from the list
  - [x] A-07.4: Implement `gate_grey_escalation(readings, proposals, current_tier)` — set GREY when any reading has `quality="fault"` and no proposal claims that reading's id as a known data fault
  - [x] A-07.5: Each gate function is pure (no I/O, no mutation of inputs)

- [ ] A-08: Implement `backend/checker/checker.py` and wire `policy.yaml` hash into the Verdict
  - [~] A-08.1: Implement `_hash_policy(policy_path)` — SHA-256 hex digest of the file bytes
  - [~] A-08.2: Implement `_default_action(tier)` — canonical action per tier from `policy.yaml`
  - [~] A-08.3: Implement `check(proposals, readings, policy_path)` applying gates in order: `worst_of → data_fault → grey_escalation → whitelist`
  - [~] A-08.4: Set `ruleset_hash` on the returned Verdict from `_hash_policy`
  - [~] A-08.5: Validate Verdict against `verdict.schema.json` before returning
  - [~] A-08.6: Mark this module as "small trusted core" — requires two reviewers on every change

- [ ] A-09: Implement `backend/api/main.py` and all route files
  - [~] A-09.1: `main.py` — create FastAPI app, register all four routers, cache validators/baselines/policy at startup, expose `GET /health`
  - [~] A-09.2: `routes/checkin.py` — validate request body, call `decide()`, return `{record_id, verdict}`; raise HTTP 422 on schema failure before calling `decide()`
  - [~] A-09.3: `routes/status.py` — read latest Record from store, return `{tier, action, reasons, record_id}`; return HTTP 404 if no records exist
  - [~] A-09.4: `routes/records.py` — paginated `GET /records` and single-record `GET /records/{record_id}`; read-only
  - [~] A-09.5: `routes/earth.py` — verify hash chain, replay with optional rules override, attach review, run rulechange diff
  - [~] A-09.6: Remove the stub from `decide()` and wire real pipeline dispatch + Checker after A-02 through A-08 pass their tests

- [ ] A-10: Implement `backend/cli.py`
  - [~] A-10.1: Implement `run-scenario` subcommand — load scenario JSON, call `decide()` per event in timestamp order, link Records via `prev_hash`
  - [~] A-10.2: Support `--limits-file` flag — load alternate `limits_table.yaml` and pass into `context["rules"]`
  - [~] A-10.3: Support `--config` flag — load alternate `a_statistical/config.yaml`
  - [~] A-10.4: Support `--seed` flag for reproducible runs
  - [~] A-10.5: Implement `replay` subcommand — re-run `decide()` with original record's inputs; support `--rules` and `--limits-file` overrides
  - [~] A-10.6: Implement `dump-records` subcommand — output records as JSON or CSV; support `--astronaut` filter
  - [~] A-10.7: Confirm `evidence/run_all.py` can drive all three subcommands without editing `backend/`

- [ ] A-11: Implement `backend/pipelines/d_llm/` (off by default)
  - [~] A-11.1: Write `prompt.md` encoding three hard rules: JSON only, may raise never lower tier, never mention dose/drug/treatment
  - [~] A-11.2: Implement `parser.py` — extract first JSON block from raw output, validate against `proposal.schema.json`, return `None` on any parse or schema failure (never raises)
  - [~] A-11.3: Implement `pipeline.py` — return `None` immediately when `LLM_ENABLED != "1"`; call LLM and pass output to parser; return Proposal or `None`
  - [~] A-11.4: Confirm that a `None` return from this pipeline is silently skipped by the orchestrator with no effect on the Verdict

- [ ] A-12: Write tests in `backend/tests/`
  - [~] A-12.1: `test_a_statistical.py` — unit tests for `baseline.py`, `cusum.py`, `patterns.py`, `pipeline.py`; PBT properties: `test_cusum_state_invariant`, `test_baseline_confidence_band_contains_mean`, `test_more_draws_narrower_band`, `test_pipeline_a_always_schema_valid`
  - [~] A-12.2: `test_checker.py` (heaviest) — unit tests for all four gate functions; PBT properties: `test_worst_of_gate`, `test_action_whitelist`, `test_data_fault_safety`, `test_llm_never_lowers`, `test_grey_escalation_on_unverified_fault`
  - [~] A-12.3: `test_api.py` — `httpx.AsyncClient` against in-process FastAPI app; test all 7 routes including HTTP 422 paths and stub Record shape
  - [~] A-12.4: `test_d_llm.py` — PBT properties: `test_parser_never_raises`, `test_parser_output_always_schema_valid`; test LLM-disabled path; test tier-monotonicity constraint

- [ ] A-13: Integration test — Storm Day scenario end to end through the API
  - [~] A-13.1: Populate `data/scenarios/storm_day.json` with events: elevated `dose_rate_usv_h`, declining `mood` and `sleep_hours`
  - [~] A-13.2: POST each event to `/checkin` via `httpx.AsyncClient` against in-process app
  - [~] A-13.3: Assert `verdict.tier` is `RED` or `GREY` on the peak storm event
  - [~] A-13.4: Assert `verdict.action` is `ALERT_CMO` or `CONTACT_GROUND_URGENT`
  - [~] A-13.5: Assert `record.hash` is consistent (re-hash and compare)
  - [~] A-13.6: Assert `record.signature` is valid HMAC
  - [~] A-13.7: Assert `record.prev_hash` links correctly across consecutive events
  - [~] A-13.8: Assert determinism — calling `decide()` twice with the same inputs returns identical `verdict`
