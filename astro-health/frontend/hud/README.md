# hud/ — helmet display

`index.html` is the helmet HUD: what one astronaut sees through the visor during
an EVA. It shows the wearer's own status and nothing else.

**The HUD decides nothing.** Every tier, action and flag on it comes from the
backend verdict. The page holds no thresholds, no medical rules and no sample
readings. With no link it shows NO LINK and hides the vitals.

## Run it

From `astro-health/`, one command starts the backend and the crew simulator, and opens all three views:

```bash
backend/.venv/bin/python run_demo.py          # Windows: backend\.venv\Scripts\python run_demo.py
```

The HUD is at http://127.0.0.1:8000/ui/hud/index.html. The page accepts these query parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `astronaut` | `eva_02` | The wearer. The HUD reads and simulates only this id. |
| `scenario` | none | Starts a simulator scenario on load: `nominal`, `exertion`, `heat`, `spe`, `hr_fault` or `spe_fault`. `run_demo.py` opens the HUD with `nominal`. |
| `met_epoch` | none | ISO time of mission start. When set, an MET clock (`MET d/hh:mm:ss`) appears above UTC. |

Browsers block sound until the page is clicked. Press **Enable audio cues** once.
Until then, the HUD shows "Audio cues off".

## Delay-aware autonomy (who can decide in time)

Every verdict gets a signed **handoff** from the backend (`backend/records/handoff.py`,
policy in `backend/checker/autonomy.yaml`). It compares how soon the verdict's action must
start with how soon Earth could answer: round-trip light time at the current distance plus
an assumed ground turnaround.

| Handoff | What the HUD shows |
|---|---|
| `GROUND_IN_LOOP` | "Earth can answer in ~2 min." (dim) |
| `ONBOARD_AUTHORITY` | A marker: "Earth answers in ~8 min: too late for this action. Act on the onboard verdict." |
| `ROUTINE` | Nothing (no time pressure) |

The top-left plate shows the distance ("Earth: Mars (closest), 3 min one way"). The latest
ground review (simulated, from the Earth view) shows as "Ground review on its way, arrives
hh:mm:ss UTC" until the light delay has passed. It then shows "Ground (simulated) agreed
with / disagreed with / asked for follow-up on your hh:mm verdict".

* **The handoff never changes a tier or an action.** Delay changes who can take part in a decision, not the decision.
* The distance is a demo setting. Use **Demo controls → Earth delay**, the Earth view's **Earth delay** selector, `POST /link`, or `run_demo.py --link mars_near`.
* Deadlines and turnaround are project-defined placeholders, not NASA values.
* `python -m evidence.autonomy` writes `evidence/results/autonomy.md`: which decisions the crew owns alone at each distance.

## Camera view and health sidebar

The HUD is camera-first. Your laptop camera fills the screen as the view through the
visor, and the health status is overlaid as a sidebar on the right edge. The camera and
hand gestures start with the page; the browser asks for camera permission once.
Add `?camera=0` to start without them. Without a camera, a drawn scene stands in.
Hand tracking runs on this device with the vendored MediaPipe Gesture Recognizer
(`../js/vendor/mediapipe/`). No camera frame leaves the page, and nothing is fetched
from the network. The camera works only on `localhost`/`127.0.0.1` or over https.

Your tracked hand is drawn over the camera image: a skeleton, a ring on your index
fingertip that fills while you pinch, and a hint saying what a pinch would do there.
The button under the ring is outlined. Key H (or the button in Demo controls) hides the
outline. It moves with your hand: it is a control aid, not health information, and the
"nothing moves" rule (BRAND.md) still holds for everything else (project decision).

| Gesture | Effect |
|---|---|
| Point with your index finger | Moves the ring; the button under it is outlined |
| **Pinch** (thumb to index) on a button | Presses it (e.g. **Acknowledge**, the sidebar tab, any demo control) |
| **Pinch** on empty space | Collapses the sidebar to the rail, or opens it again |
| Flat open hand, swipe right / left | Collapse / open the sidebar |
| Hold an open palm still | **Expanded** sidebar: wider, larger text, still at the edge ([V2 11022] 11.1.6.5) |
| Hold a fist still | **Normal** sidebar |

The collapsed **rail** keeps the tier word, shape and action. Only nominal vitals are
hidden; a flagged or unusable vital always stays. The tab on the sidebar's edge, the keys
D, N and E, and the buttons in **Demo controls** (key C) do the same. Demo controls also
hold the scenario simulator and the audio switch.

**Acknowledge (dismiss).** A non-GREEN verdict shows an **Acknowledge** button. Pressing it
(by pinch, click or keyboard) calls `POST /records/{id}/ack`. That logs a signed
acknowledgement in the backend's own hash-linked chain, so Earth can tell "shown" from
"confirmed seen". It **never hides or changes the tier or the action**. The HUD then shows
"Acknowledged hh:mm:ss UTC" for as long as the same status lasts: the same tier, action,
extra actions and triggered rules, across new check-ins. A different status or a new cause
(e.g. radiation after heat) shows the button again (project decision).

Pinch detection details (in `TUNING`): the thumb-to-index gap is measured against palm size
with hysteresis, so a held pinch fires once. The index finger must be extended, so a fist
never counts. A pinch acts where the fingertip was about 120 ms before it closed, because
closing the fingers moves the tip. Swipes count only with a flat open hand, so moving a
pointing finger across the screen never triggers one.

* Gestures change only the sidebar. They never touch a verdict, a reading or the backend.
* **Any change of status (tier, NO LINK, fail-safe) reopens the normal sidebar at once.** A docked HUD can never keep a new alert out of view (project decision).
* Switches are instant. Nothing animates (BRAND.md).
* Vitals sit in the sidebar under the status, not bottom-left as BRAND.md describes. This is a project decision for the camera-first layout. The centre of the view stays clear.
* Interpretation thresholds (swipe distance and time, hold time, confidence, cooldown) are in `TUNING` in `gestures.mjs`. They are project decisions tuned for a laptop webcam, not suit hardware. `GestureInterpreter` is pure and can be tested with synthetic frames.
* The camera `<video>` sits outside the React root. The vendored React-compatible runtime rebuilds the DOM on every render and has no refs, which would destroy a video element inside it.

## What it reads

| On screen | Source |
|---|---|
| Tier word, shape, colour | `GET /status/{id}` → `tier`. Words from `Vitalis.TIERS`. |
| Action | `action`, worded by `Vitalis.ACTIONS`. Free text is never used. |
| "Also: …" line | `additional_actions` (a GREY verdict that hides a known RED). |
| Split marker | `disagreement_status` when it is not `AGREEMENT`. |
| "Decision system failed" | `GET /records/{record_id}` → `verdict.failsafe`. |
| Vitals (up to four) | The record's `readings` for the wearer. |
| Vital highlight and ▲/▼ | `verdict.decision_trace.triggered_rules`. A rule id is `<channel>.<bound>` (e.g. `heart_rate.red_high`). The bound's own name gives the colour (`red_*`, `yellow_*`) and the side gives the arrow (`*_high` ▲, `*_low` ▼). For any other rule (e.g. `heart_rate.unit`), the colour is the tier of the pipeline that raised it, from `decision_trace.contributing_proposals`. |
| "No data · Sensor fault" on a vital | `integrity.readings[].status` is not `valid`. The number is hidden. |
| "Not assessed" on every vital | The verdict is a fail-safe, so no reading was judged. Values show at full ink on a dashed GREY plate, never dim. |

## Failure states

* **Backend unreachable.** The first failed poll (every 3 s) switches to NO LINK in the GREY style, showing the time of the last verdict. Vitals are hidden. Nothing local takes over.
* **GREY verdict.** Treated as urgent: it gets the heaviest border (4px dashed) and the warning tone, and ranks above RED.
* **Fail-safe verdict.** GREY plus a red-bordered "Decision system failed" marker.
* **No verdict yet (404).** GREY "No data" with no action, because there is no verdict to authorize one.
* **Old verdict.** Its time and age are always shown ("Verdict 21:20:17 UTC, 6 s old"), so an old GREEN never reads as a live all-clear. The HUD does not turn an old verdict GREY. That would be a staleness rule, and rules belong in the backend (see Open questions).

## Scenario simulator

The buttons under the visor POST honest readings to `/checkin` every 5 s:

* Units from `backend/checker/policy.yaml` (`bpm`, `C`, `ppm`, `uSv/h`), `source: "simulated"`, and the current timestamp.
* Each scenario is a physiological situation (steady work, heavy exertion, heat stress, solar particle event, heart-rate strap fault, or both). The backend decides what each one means.
* Small sensor noise keeps values moving, as a real sensor does. The backend treats 8 identical heart rates as a stuck sensor.
* A strap fault sends the sensor's last held value with `quality: "fault"`. No value is ever changed to force a result.
* Cabin CO2 (`co2_ppm`) is shown because the backend has no suit CO2 or oxygen channel. Every simulated value is labelled "Simulated", and the HUD shows "Simulated input" whenever the record contains simulated readings.

## Testing the fail-safe display

A normal check-in cannot honestly produce a fail-safe verdict. It appears only when `decide()` itself fails. To see it, inject a fault into the real orchestrator in a throwaway app (do not commit it):

```python
# failsafe_app.py, outside the repo; run with PYTHONPATH=astro-health:<its dir>
import backend.orchestrator as orch
def _broken(*a, **k): raise OSError("policy store unreadable (injected test fault)")
orch.load_policy = _broken
from backend.api.main import create_app
app = create_app()
```

Run `SIGNING_KEY=… uvicorn failsafe_app:app --port 8000`, then POST any check-in. The HUD shows GREY, "Contact ground, urgent", "Decision system failed", and every vital "Not assessed".

## Where each rule comes from

NASA citations are to **NASA-STD-3001 Volume 2, Revision F** (approved 2026-07-14, the active revision on standards.nasa.gov/node/237). Each citation is also a comment in `index.html` beside the code that applies it. This page has not been verified against the standard. It applies the requirements listed here, and a list is not a claim of conformance.

### Cites NASA-STD-3001 Vol. 2 Rev. F

| Requirement | Where it shows on the HUD |
|---|---|
| [V2 10045] 10.4.2.2 Color Coding Redundancy; App. F.5.10 e | The tier always has a word and a shape as well as a colour. Flagged vitals add a glyph and an arrow. |
| Table 10.4-3 Indicator Light Characteristics; App. F.6.4 a–b; Table F.5-1 | Red means warning/failed (RED "Act now"). Yellow means caution (YELLOW "Watch"). |
| [V2 10114] 10.3.1 Distinguishable and Consistent Alerts | Each change of status gets both a visual change and an audio cue. |
| Table 10.3-1 Alert Type and Annunciation | Tone patterns: Warning is alternating 400/1,024 Hz square, 0.4 s each, 1.6 s then 1 s silence, ×2. Caution is a 512 Hz triangle wave, 1 s on, 1 s off. Advisory is 900 Hz sine, 106/106/106 ms. |
| [V2 10058] 10.3.11 Auditory Alert Frequency | Every tone is between 200 Hz and 4 kHz. |
| [V2 10176] 10.3.3 Reduced Initial Alert Annunciation Level | The first sequence plays 10 dB below the second. |
| [V2 10066] 10.4.3.3 Label Font Height | No HUD text is smaller than 16 px (12 pt). |
| App. F.5.1 b, d, h | Sans serif text, a fixed-width font for numbers, and mixed case for words that are not acronyms. |
| App. F.5.10 f (contrast ≥ 6:1) | Words are always `--ink`: 8.8:1 on the 78% plate over pure white, the worst case. Dim nominal values use an ink/ink-muted mix at 6.5:1. Tier colours appear only on shapes, borders and arrows, because red text on that plate measures 3.2:1. |
| [V2 10046] 10.4.2.3 Measurement Units; App. F.5.6 b, c, f | A unit follows every value. Decimals are padded, never rounded. Leading zeros are kept (`0.58`). |
| App. F.4.3.1 c (stale data indication) | NO LINK with the last verdict time, plus the age of every verdict. |
| App. F.4.3.1 d (coloured up/down arrow after an out-of-limit value) | ▲ or ▼ in the tier colour, taken from the rule id's bound. |
| App. F.4.2 f (dedicated always-visible area for time, alerts and link status) | The top-left plate holds the clock, the wearer and the link state. |
| App. F.4.2 j (sim mode visually distinct) | A "Simulated input" marker with the `--sim` border. |
| App. F.6.1 e–f (time labelled, 24-hour, `MET d/hh:mm:ss`) | `UTC hh:mm:ss`, plus MET when `met_epoch` is set. |
| [V2 11022] 11.1.6.5 Suit Helmet Displays (field of regard unencumbered) | The centre of the view stays clear. Everything sits at the edges. |
| [V2 10037] 10.4.2.1 Simultaneous Display of Critical Information | Tier, action and any additional action are on screen together, with no paging. |
| App. F.5.11 a (flashing reserved for immediate action) | Nothing flashes. Table 10.3-1 uses flashing red only for Emergency, and the HUD has no Emergency class. |

### Requirements read but not met, or not applicable

| Requirement | Status |
|---|---|
| Table F.5-1: **cyan** for "Missing or stale data"; gray for "Unavailable, unselectable" | **Not followed.** GREY "No data" uses `--tier-grey`, because the tier palette is the project-wide contract (BRAND.md) and the HUD should match the tablet and Earth views (App. F.4.1 f). Adopting cyan would be a brand-wide decision. |
| Table 10.3-1 "repeat until terminated"; [V2 10116] 10.3.9 Alert Silencing; [V2 10177] 10.3.8 Suppression; App. F.6.4 d–k (acknowledge, counts, queue) | **Not implemented.** Each needs an acknowledgement, and recording one needs a new backend endpoint (out of scope). The cue plays once per change of status. |
| [V2 10056] 10.3.12 Alert Sound Level; [V2 6081] 6.6.1.10 | Cannot be met by a web page, because speaker output is not calibrated. |
| [V2 11035] 11.3.3, [V2 11036] 11.3.4 (display suit pressure, ppO2, ppCO2) | **Not met.** The backend has no suit channels. Cabin CO2 is shown instead. |
| [V2 11023] 11.1.7 Suit Information Management (consumables) | Not met: no consumables channel in the backend. |
| [V2 10048] 10.4.2.4 / Table 10.4-2 Visual Display Parameters | Written for IVA displays, and luminance and resolution belong to the hardware, not this page. |
| [V2 5051] 5.1.7 Legibility ("under expected operating conditions") | Approached through the plate, contrast and size rules above. Not verified in a real helmet. |
| App. F.5.1 g (character height ≥ 0.25°, 0.4° preferred) | Depends on the HUD's optical viewing distance, which is not known here. 16 px meets [V2 10066]'s 12 pt alternative on a monitor. |
| Gloves: Table 10.4-4 Control Spacing, [V2 10157] 10.4.4.4 | Not applicable: the HUD has no controls in the visor. The demo controls below it use 48 px targets (BRAND.md). |
| Data-validity indication as a numbered requirement | No numbered [V2] requirement was found. App. F.4.3.1 c (stale data) is the closest, and it is applied. |

### Research-backed (suit-display prototypes, not NASA requirements)

* Information sits at the edges of the field of view, not over the outside view.
* Every change of status pairs a visual change with an audio cue. In a University of Maryland HUD study, display plus audio lowered workload and task time compared with either alone.
* No peripheral cue is used on its own. In NASA Johnson / UC Davis testing, peripheral cues worked only in some scenarios, so a tier change always carries a word and a shape.

### Project decisions

* **GREY ranks above RED** (policy.yaml: GREY means the data cannot be verified). It gets the heaviest border and the warning tone.
* **Tone mapping:** RED, GREY, NO LINK and fail-safe use the Warning pattern; YELLOW uses Caution; a return to GREEN uses Advisory. The standard has no class for "cannot verify".
* **Night palette always**, with every element on a `--void` plate at 78% opacity (BRAND.md).
* **Nothing moves.** The clock and verdict age change text, but nothing animates (BRAND.md).
* **Values at 34 px** (BRAND.md). Time top-left; status and vitals in the right-edge sidebar (camera-first layout, see above).
* **Nominal values dim; only flagged values take a tier colour and glyph** (BRAND.md).
* **Which four vitals:** fixed slot order (heart rate, body temp, cabin CO2, dose rate, …). A flagged or unusable channel always takes a slot.
* **Unusable readings hide their number** and show "No data" with the reason (BRAND.md: "No data is not good news").
* **No local acknowledge button and no "3 readings in a row" rule.** The BRAND.md helmet section describes both, but they belong in the backend (see below).
* **Polling every 3 s** (`/status`); the simulator posts every 5 s.

## Open questions (need a backend change; not done here)

* **Flicker suppression** ("3 out-of-band readings in a row") belongs in the Checker policy, not the page.
* **Acknowledgement** needs a backend endpoint to record it. Silencing, repeat-until-acknowledged tones and App. F.6.4 all depend on it.
* **Verdict staleness.** Should the backend (or `/status`) mark a verdict stale after N seconds? Today the HUD only shows its age.
* **Suit channels** (suit CO2, ppO2, pressure, O2 remaining) would let the HUD meet [V2 11035]/[V2 11036].
* **Cyan for missing/stale data** (Table F.5-1) would be a brand-wide palette change.
