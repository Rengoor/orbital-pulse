# backend/

**Owner:** person A (pipelines A and D, Checker, orchestrator, API) and person B (pipeline B, records, downlink, Earth)

Everything that decides, records and verifies. Core idea: one pure `decide()` in `orchestrator.py` (time passed in, no hidden state), so Earth's replay is the same function with the same inputs.

## Rules for this folder

- Pipelines are blind: none sees another's output.
- Escalate freely, downgrade only on a confirmed data fault.
- The LLM pipeline may raise a flag, never lower a tier, never suggest a dose.
- Pipeline A (person A) and pipeline B (person B) are written independently on purpose.
- Log first, display second: the signed record is written before the verdict is shown.
- Validate all objects against `../data/schemas/`.
- Thresholds in `limits_table.yaml` are placeholders until sourced from NASA documents.