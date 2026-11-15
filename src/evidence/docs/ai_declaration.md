# AI-use declaration

NASA Space Apps Challenge 2026 asks teams to declare how artificial intelligence was used. This is Orbital Pulse's declaration.

## What was used

- **Claude (Anthropic), through Claude Code**, as a coding assistant while writing code, tests and documentation in this repository.
- No other AI tool was used. No AI-generated images, audio or video appear anywhere in the project.

## How the record is kept

- Commits in which the assistant helped carry a `Co-Authored-By: Claude ...` trailer in their commit message. The git history is the authoritative, per-commit record of where AI assistance was involved.
- Commits without that trailer were written by the team alone.

## What the team is responsible for

- The design of the system (blind pipelines, the deterministic Checker, GREY as a first-class tier, the signed hash-chained records, delay-aware autonomy, Earth replay) is the team's. The assistant implemented and refactored under the team's direction and review.
- Every line of code was read and run by a team member before it was committed.
- Every number reported in the README, in `evidence/results/` and in `validation/results/` comes from a real run of the committed code by the team or by the CI workflow in `.github/workflows/ci.yml`. Nothing was typed in from an assistant's claim.
- The NASA data under `data/nasa/` and `validation/data/` was fetched from NASA services by the team's own scripts; the manifests record each source URL, query, fetch time and checksum.

## What the AI did not do

- It did not decide any medical threshold. All thresholds are project-defined placeholders and are labelled as such (`evidence/docs/limits.md`).
- It is not part of the running system. The optional onboard LLM pipeline (`backend/pipelines/d_llm/`) is a separate, local, Ollama-based component that is off by default and has only been exercised with canned replies.

## NASA branding

No NASA logos, flags, mission identifiers or insignia are used or modified anywhere in this project.
