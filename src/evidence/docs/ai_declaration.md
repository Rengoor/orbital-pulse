# AI-use declaration

NASA Space Apps Challenge 2026 asks teams to declare how artificial intelligence was used. This is Orbital Pulse's declaration.

## What was used

- An AI coding assistant (a large language model used from the team's editor) while writing code, tests and documentation in this repository.
- No AI-generated images, audio or video appear anywhere in the project.

## How the record is kept

- This document is the declaration. The assistant is not listed as a contributor or co-author anywhere in the repository; all commits are authored by the team members who reviewed and ran the work.

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
