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

## Offline by construction

The whole system, advisor included, runs with no internet connection. What enforces that:

| Path | Guard | Where |
|---|---|---|
| Advisor → model | `OLLAMA_HOST` must be an `http://` URL on `localhost`, `127.0.0.1` or `::1`; anything else raises before any request is made. The client ignores proxy environment variables (`trust_env=False`). | `pipeline.py` → `_require_loopback_host`, `call_llm`; pinned by `tests/test_d_llm.py` |
| What the model sees | Readings as channel, value, unit, time and quality. No astronaut identifier, no record ids, no free text from outside the readings. | `pipeline.py` → `_READING_FIELDS`, `feedback.py` → `summarise_readings` |
| Views → backend | The browser client only ever calls the origin the page was served from, or a `?api=` override that must be loopback. | `frontend/js/api.js` |
| Views → anywhere else | Every page carries a Content Security Policy with `connect-src 'self'`. This blocks the usage-logging call built into the vendored MediaPipe gesture bundle, which would otherwise post to a Google endpoint every 60 seconds. | `<meta http-equiv="Content-Security-Policy">` in each page; pinned by `backend/tests/test_frontend_integration.py` |
| Scripts, fonts, models | React, MediaPipe and the gesture model are vendored and hash-pinned. Fonts are system fonts; nothing is fetched from a CDN. | `frontend/js/vendor/`, `frontend/css/tokens.css` |
| NASA data | Fetched once by explicit scripts (`data/nasa/*/fetch.py`, `validation/fetch.py`) and committed as small processed files. The running backend reads only those files. | `data/nasa/README.md` |

Before an offline run, pull the model while still online (`ollama pull llama3.2`); Ollama serves it from local disk after that. The Ollama server itself is outside this repository; run it with network access removed if the deployment requires proof rather than configuration.

## Limits

* Ground truth is a simulated reviewer; no clinician has confirmed a tier.
* The advisor has only been exercised with canned replies. Whether in-context corrections actually improve a given local model is unmeasured until that test is run.
* Trust is a project-defined scalar, not a calibrated probability.
