# AI-use declaration

AI tools were used to write code and documentation in this repository:

- **Claude Code** (Anthropic), with the models Claude Fable 5, Claude
  Fable 5.2 and Claude Opus 5.5. Used for drafting backend and frontend code,
  tests, the evidence runners and documentation, working from written
  specifications and review by the team.
- AI-assisted commits are marked in the git history with
  `Co-Authored-By: Claude ...` trailers; the history is the authoritative
  record of which changes were AI-assisted.

The team reviewed and ran the code. All reported results come from runs by
the team or its CI (script: `python -m evidence.run_all --seed 42`); no
number in `evidence/results/` is AI-estimated.

The LLM **inside** the product (pipeline `d_llm`) is disabled by default,
advisory only (it can raise a tier, never lower one), restricted to a local
Ollama endpoint on loopback, and its output passes a parser and grounding
check before the Checker sees it. As of 2026-11-14 it has been tested only
against canned replies, not a real local model; that status is also stated
in `limits.md`.

No AI-generated images are used in the submission at the time of writing; if
any are added they must carry a visible watermark. No NASA logos or mission
identifiers are used.
