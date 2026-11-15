Orbital Pulse is the interface for the astronaut health monitor: decision support, not diagnosis. Crew see one body, holographic and drifting as if weightless, with hotspots that show what's wrong and one thing to do about it. An onboard LLM advisor suggests actions, and a deterministic Checker can only *raise* the advisor's verdict, never lower it. The UI must never talk itself into reassuring anyone.

Load `tokens.css`, then `components/bundle.css`, then React 18 and `components/bundle.js`. Components live on `window.OrbitalPulse`. The three type families come from Google Fonts; `bundle.css` imports them.

## Content fundamentals

- **Status first, then one action.** Every screen leads with the tier and a single imperative: "Rest and hydrate", "Alert the crew medical officer". Reasons and provenance come after, on demand.
- **Say what you know, and how you know it.** Put a `SourceLabel` next to every value: `REAL · NASA OSDR` or `SIMULATED`. Never leave a number unlabelled.
- **No data is not good news.** A missing reading is GREY, shown as "No data" with a dashed ring. Never print a placeholder that reads as normal (`0`, `--` in green).
- **Plain, calm, specific.** Write "Heart rate 19 bpm above baseline during a solar particle event", not "Abnormal cardiac activity detected!". No exclamation marks, no emoji, no "Great news".
- **Units always, numbers exact.** `96 bpm`, `3850 ppm`, `0.42 µSv/h`, `36.8 °C`. Times in mission elapsed time plus UTC: `MET 142:06 · 09:12Z`.
- **Casing.** Labels and badge words are uppercase via the `label` style; headlines and actions are sentence case.
- **Address the crew member directly**, in the second person and imperative: "Sit for 10 minutes, drink 300 ml and recheck."

## Visual foundations

**Colour.** `void` is the page and `hull` is every panel. `holo` is the hologram: the body wireframe, sparklines, selection and the focus ring. `signal` (suit orange) is reserved for the single primary action on a view and the brand mark. It is never a status. Text is `ink` or `ink-muted` and reads at 6:1 or better on `void`, `hull` and `hull-raised` in both themes. `sim` appears only on the SIMULATED chip.

**Tiers.** These are the contract with the Checker (`card.schema.json`): GREEN Nominal, YELLOW Watch, RED Act now, GREY No data. Each tier always carries three signals: colour (`tier-*`), shape (check circle, triangle, octagon, dashed ring) and its word. At night GREEN and RED differ by less than 3:1 in lightness, so never show a tier by colour alone. Use the `tier-*-wash` tokens for tinted backgrounds. Only RED gets `glow-alert` and the pulse.

**Themes.** `night` is the default (cabin night lighting, dark-adapted eyes). `day` is for lit modules and daylight demos. Both share every token name; never hard-code a hex value.

**Type.** `display-xl` (Unbounded) is used once per screen, for crew state. `display` is for screen titles and `title` for card headlines. `body` and `body-sm` (Instrument Sans) carry advisor text and reasons. `label` sets channel names, uppercase and tracked at 0.14em. Every number uses the IBM Plex Mono styles `readout-xl`, `readout` and `data`, with tabular numerals so digits don't jitter as live values change.

**Space and size.** Use a 4px base (`space-1` to `space-12`). Panels pad at `space-4` on dense dashboards and `space-6` in detail views. Every touch target is at least `space-12` (48px), because crew may wear gloves and float.

**Shape.** Panels use `radius-md` with two `holo` corner brackets; a bracketed panel means a live instrument. Buttons use `radius-sm` with one cut corner (top-right). Hotspots, crew avatars and the segmented thumb use `radius-pill`. Chips and badges use `radius-xs`.

**Depth.** Every Panel gets `panel` shadow. At night, `glow-holo` marks the selected element; by day it becomes a crisp 1px edge. Use no other shadows and no gradients except the SIMULATED hatch.

**Motion.** Motion carries meaning. The body drifts ±5px, since nothing sits still in microgravity. Hotspot rings ping, faster on RED. A scanline on a Panel means the feed is streaming. Advisor text streams in as it is generated, and the Checker stamp appears only when it's done. `prefers-reduced-motion` stops all of it, and every motion has a static equivalent.

**Focus.** Use a solid 2px `holo` outline with a 2px offset. It reaches at least 3:1 on `void` and `hull` in both themes.

## The three views

One data model (`zones`, a `card`, an `advice` string) drives three views of the same crew member. Switch between them with `SegmentedControl` (Holo body / Dashboard / AR). The `MissionConsole` page shows them wired together.

- **Holo body:** `BodyMap` beside a stack of `VitalReadout`s. Clicking a hotspot or a readout selects the same zone, and the `Advisory` answers for that zone.
- **Dashboard:** a three-column grid of `VitalReadout`s, a `DoseGauge` and an `Advisory` summary. Use it for the CMO's review, or whenever a glance at everything matters more than location.
- **AR:** in a WebXR `immersive-ar` session, the same `BodyMap` zone ids anchor to a surface. Keep hotspot hit areas at 18px radius in SVG space (about 48px at arm's length), keep `void` behind text panels, and use the same callout. Where WebXR AR isn't supported, fall back to the in-cabin preview: the body over a perspective floor grid.

Body zones (`OrbitalPulse.ZONES`) map to reading channels: `neuro` (sleep_hours, mood), `resp` (co2_ppm), `cardio` (heart_rate, bp_*), `radiation` (dose_rate_usv_h), `metabolic` (glucose, blood_analyte), `thermal` (temperature), `msk` (exercise_minutes).

## The advisor and the Checker

Show the LLM's suggestion only inside `Advisory` (and its proposal inside `DecisionCard`'s chain), always followed by the Checker's stamp: Confirmed, Escalated, Blocked or Awaiting. When the Checker overrules the advisor, show both steps and strike through the advisor's action; never hide the disagreement. A blocked suggestion stays visible, struck through in `ink-muted`.

## Helmet display and station tablet

The same Checker verdicts feed two more surfaces, each with its own rules.

**Helmet display (`HelmetHUD` page).** It shows the wearer's own data and nothing else.
- Render it in the `night` palette at all times; it is an emissive display. Put every element on a `void` plate at about 78% opacity so it reads against sunlit regolith and black sky.
- Nothing moves: no drift, scanline, ping or streaming text. Use 13px text or larger, with values at 34px, because many crew lose some near vision in flight.
- Keep the centre of the view clear. Status goes top-right, mission time and oxygen top-left, four vitals bottom-left and a small figure marking the affected zone bottom-right.
- Nominal values sit in `ink-muted`; only flagged values take a tier colour and glyph.
- A flag commits only after 3 consecutive out-of-band readings; until then, show a dashed "Checking 1/3" plate with no action. A committed flag shows the value, the tier word and one action, and can be acknowledged by voice or a suit button.
- The LLM never runs in the suit. The suit runs the Checker locally; the advisor stays in the habitat.

**Station tablet (`StationTablet` page).** It has three roles, following flight-surgeon confidentiality.
- **Commander** sees every crew member's tier, required action and EVA go/no-go, plus shared habitat data. Medical detail appears only when that crew member shares it.
- **CMO** sees full detail for everyone, and every record opened is logged.
- **My health** shows your own full detail, with a 7-day trend view, a sharing switch and a private line to the flight surgeon.
- Habitat environment data (cabin CO2, dose rate, space weather) is not personal, and every role sees it.

## Iconography

Icons come from the system's own 24px stroke set (`OrbitalPulse.Icon`, stroke 2, round caps and joins, `currentColor`). Tier shapes, actions (`clock`, `drop`, `card`, `medic`, `antenna`, `check`), views (`body`, `grid`, `cube`) and `shield`, `flare`, `sun`, `arrow` are included. Icons always sit beside a word, except the hotspot glyphs, which carry an `aria-label`. No emoji. There's no logo file yet: the wordmark is "Orbital Pulse" set in `display` with a `signal` full stop.
