# Pipeline D: the onboard advisor (local LLM) and its feedback loop

Pipeline D is an optional local language model (Ollama on loopback, `LLM_ENABLED=1`). It is **advisory**: it may raise a tier, never lower one, never names a dose or drug, and is discarded if it cites anything it was not given. It is **never a vote**: the Checker's floor (`backend/checker/checker.py`, `advisory_floor`) guarantees the verdict is at least what pipelines A and B produce on their own.

## The feedback loop (new)

```
decision ──► control centre reviews it ──► lesson ──► signed ledger ──► trust ──► next prompt
             AGREE  = confirms recorded tier     (advisor said X,    (chain, like     (reward /    (recent
             DISAGREE + confirmed tier           ground confirmed Y)  every log)       punish)     corrections)
             FOLLOW_UP = teaches nothing
```

| Step | Where | What it does |
|---|---|---|
| Review | `POST /earth/review` with `outcome` and optional `confirmed_tier` | Earth states what the tier should have been. Never changes the record. |
| Lesson | `feedback.py` → `lesson_from_review` | Compares the advisor's tier in the record with the confirmed tier: `correct`, `over_call` (false alarm), `under_call` (missed risk), `abstained` (no usable output). |
| Ledger | `store.add_llm_lesson` (table `llm_feedback`) | Hash-chained and signed, same as records, reviews, acks and handoffs. `GET /earth/llm-feedback` verifies it. |
| Trust | `feedback.py` → `trust_from`, numbers in `feedback.yaml` | Starts at 0.5. Correct +0.08, false alarm −0.05, **missed risk −0.15**, abstained −0.02. Clamped to 0..1. |
| States | `feedback.yaml` → `trust.states` | `untrusted` (< 0.35): proposal **withheld** from the Checker. `probation` (< 0.60): passed, labelled. `trusted`: passed. All three remain advisory. |
| Learning | `pipeline.py` → `build_system_prompt` | `prompt.md` plus the track record and the most recent corrections and examples. **No model weights change on board.** |
| Export | `python -m backend.pipelines.d_llm.feedback export` | The ledger as a JSONL fine-tuning dataset for offline training on the ground, with the label basis on every line. |

Every value in `feedback.yaml` is project-defined and hashed into each record's `execution_manifest.llm.feedback`, so the record says which feedback state the advisor was shown.

## How the HUD and the other views connect

| View | Source | What it shows |
|---|---|---|
| Helmet HUD | `GET /status/{id}` → `advisor` | One dim line: what the advisor said (or `withheld` / `no usable output`), live trust and state, "advisory only". Never the tier: the tier is the Checker's. |
| Crew monitor | `GET /records/{id}/trust` → `advisor` | A row in "Why should I trust this decision?" with the advisor's tier, trust and scored lesson count at decision time. |
| Earth base | `GET /earth/llm-feedback`, `POST /earth/review`, `POST /earth/llm-feedback/nasa-examples` | The review form gains "the tier should have been"; a panel shows trust, accuracy, correct / false alarm / missed risk / abstained counts, ledger integrity, recent corrections, and a button to load NASA worked examples. |

## How NASA test data is used

* **Worked examples (now).** `examples_from_nasa` turns the real Inspiration4 glucose draws (`validation/data/inspiration4_glucose.json`, OSDR OSD-575) into prompt examples. The label is the **laboratory reference range** published with the dataset (in range GREEN, out of range YELLOW). It is labelled as such on every example: not a flight surgeon, not a NASA medical limit. Examples are shown to the model and **never scored**, so they cannot move trust.
* **Scored validation (next).** `validation/run.py` already runs real ALTEA dose-equivalent and Inspiration4 glucose through the decision system. With a real local model enabled, the same runs give the advisor's tier per real measurement, and the reference range gives a confirmed tier, so accuracy can be measured on real data before any flight-surgeon review exists.

## Limits

* Ground truth is a simulated reviewer; no clinician has confirmed a tier.
* The advisor has only been exercised with canned replies. Whether in-context corrections actually improve a given local model is unmeasured until that test is run.
* Trust is a project-defined scalar, not a calibrated probability.
