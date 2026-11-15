# backend/

Everything that decides, records and verifies. Core idea: one pure `decide()` in `orchestrator.py` (time passed in, no hidden state), so Earth's replay is the same function with the same inputs.

| Path | What it holds |
|---|---|
| `orchestrator.py` | `decide()`: input gate, blind pipelines, Checker, signed record; fail-safe GREY record if any stage breaks |
| `checker/` | The deterministic referee (`checker.py`, `gates.py`), the integrity gate (`input_gate.py`), the versioned policy (`policy.yaml`) and delay-aware autonomy deadlines (`autonomy.yaml`) |
| `pipelines/` | `a_statistical/` (baselines + CUSUM), `b_limits/` (absolute limits table), `d_llm/` (optional local LLM, advisory, off by default). Discovered by folder |
| `records/` | Hash chain and canonical JSON (`chain.py`), HMAC signing, store (memory or SQLite), decision cards, acknowledgements, checkpoints (`anchor.py`), autonomy handoffs |
| `downlink/` | Light-delay model and the prioritised downlink queue |
| `earth/` | Ground-side tools: chain verification, byte-for-byte replay, signed reviews, rule-change replay |
| `api/` | FastAPI app; also serves the frontend at `/ui/` |
| `cli.py` | Run a scenario, replay a record, dump records, write or verify a checkpoint |
| `tests/` | Unit, API, governance, red-team and end-to-end storm-day tests |

## Rules for this folder

- Pipelines are blind: none sees another's output.
- Escalate freely, downgrade only on a confirmed data fault.
- The LLM pipeline may raise a flag, never lower a tier, never suggest a dose or a drug.
- Log first, display second: the signed record is written before the verdict is shown.
- Validate every object against `../data/schemas/`.
- Thresholds in `pipelines/b_limits/limits_table.yaml` are project-defined placeholders, declared as such in every row.
