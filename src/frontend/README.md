# frontend/

The Orbital Pulse front end: design tokens, a React component library and three views, one directory each: the helmet HUD (`hud/`), the crew health monitor (`tablet/`) and the Earth base display (`earth/`). No build step: plain HTML, CSS and one JavaScript file, with React 18 vendored under `js/vendor/`.

**Views display; they never decide.** No tier, threshold or medical rule exists in any file here. Every verdict is read from the backend, and a view with no backend link shows an explicit NO LINK state rather than stale or sample data.

## Run it

The backend serves this folder at **http://127.0.0.1:8000/ui/**. From `src/`:

```bash
backend/.venv/bin/python run_demo.py      # backend + simulator, opens all three views
```

Add `?theme=day` to any URL for the day theme. Opening the HTML files without the backend shows the NO LINK state by design.

## What's where

| Path | What it is |
|---|---|
| `index.html` | Start page linking every view and component demo |
| `hud/index.html` | **View 1, helmet HUD.** The wearer's own tier, action and vitals, camera-first with point-and-pinch control (`hud/gestures.mjs`, MediaPipe vendored). Display rules cite NASA-STD-3001 Vol. 2 in `hud/README.md` |
| `tablet/monitor.html` | **View 2, crew health monitor.** Every channel, the verdict, and the "why should I trust this" panel. See `tablet/README.md` |
| `earth/index.html` | **View 3, Earth base.** Every log (decisions, chain, checkpoints, downlink, reviews) with verify, replay, review and rule-change testing. See `earth/README.md` |
| `components/*.html` | One live demo per component |
| `js/orbitalpulse.js` | The component library. Defines `window.OrbitalPulse` (BodyMap, VitalReadout, Sparkline, DoseGauge, DecisionCard, Advisory, TierBadge, SourceLabel, DelayDial, CrewSwitcher, SegmentedControl, Button, Panel, Icon) |
| `js/api.js` | The only place the views talk to the backend (`window.OrbitalPulseAPI`) |
| `js/vendor/` | React 18, ReactDOM and MediaPipe, pinned by checksum in `backend/tests/test_frontend_integration.py` |
| `css/orbitalpulse.css` | Component styles. Every colour, space and radius is a token |
| `css/tokens.css` | CSS custom properties for both themes, generated from `tokens/tokens.json` |
| `tokens/tokens.json` | Source of truth for colours, type, spacing, radii and shadows |
| `types/index.d.ts` | Prop types for every component (documentation) |
| `BRAND.md` | Usage rules: tiers, copy, motion, helmet and tablet rules, privacy |

## Using the components in your own page

```html
<link rel="stylesheet" href="css/tokens.css">
<link rel="stylesheet" href="css/orbitalpulse.css">
<script src="js/vendor/react.production.min.js"></script>
<script src="js/vendor/react-dom.production.min.js"></script>
<script src="js/orbitalpulse.js"></script>
<div id="root"></div>
<script>
  var V = window.OrbitalPulse, h = React.createElement;
  ReactDOM.createRoot(document.getElementById('root')).render(
    h(V.VitalReadout, { label: 'Heart rate', value: 96, unit: 'bpm', tier: 'YELLOW', source: 'simulated' }));
</script>
```

The tier and action strings match `data/schemas/card.schema.json` and `verdict.schema.json`; `source` values match `reading.schema.json`. Component demos use illustrative values, never medical limits.
