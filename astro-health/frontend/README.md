# vitalis-ui

The Vitalis front end: design tokens, a React component library and three views, one directory each: the helmet HUD (`hud/`), the tablet (`tablet/`) and the Earth base display (`earth/`). No build step: plain HTML, CSS and one JavaScript file, with React 18 loaded from jsDelivr.

## Run it

From this folder:

```bash
python -m http.server 8080
```

Then open http://localhost:8080. Add `?theme=day` to any URL for the day theme.

Opening the files straight from disk (`file://`) also works in most browsers, but a local server is more reliable.

## What's where

| Path | What it is |
|---|---|
| `index.html` | Start page linking every screen and component |
| `hud/index.html` | **View 1, helmet HUD.** The wearer's own tier, action and vitals, live from the backend only; NO LINK when unreachable. See `hud/README.md` |
| `pages/helmet-hud.html` | Earlier helmet display prototype, kept for reference |
| `tablet/index.html` | **View 2, tablet.** Advanced health monitoring: Commander, CMO and My health roles with medical-privacy gating |
| `tablet/crew-console.html` | Tablet crew console: Holo body / Dashboard / AR views, crew switcher, decision card, advisor |
| `earth/index.html` | **View 3, Earth base.** Every log (decisions, chain, checkpoints, downlink, reviews) with verify, replay and review |
| `components/*.html` | One live demo per component |
| `js/vitalis.js` | The component library. Defines `window.Vitalis` (BodyMap, VitalReadout, Sparkline, DoseGauge, DecisionCard, Advisory, TierBadge, SourceLabel, DelayDial, CrewSwitcher, SegmentedControl, Button, Panel, Icon) |
| `css/vitalis.css` | Component styles. Every colour, space and radius is a token |
| `css/tokens.css` | CSS custom properties for both themes, generated from `tokens/tokens.json` |
| `tokens/tokens.json` | Source of truth for colours, type, spacing, radii and shadows |
| `types/index.d.ts` | Prop types for every component (documentation) |
| `BRAND.md` | Usage rules: tiers, copy, motion, helmet and tablet rules, privacy |

## Using the components in your own page

```html
<link rel="stylesheet" href="css/tokens.css">
<link rel="stylesheet" href="css/vitalis.css">
<script src="https://cdn.jsdelivr.net/npm/react@18.3.1/umd/react.production.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/react-dom@18.3.1/umd/react-dom.production.min.js"></script>
<script src="js/vitalis.js"></script>
<div id="root"></div>
<script>
  var V = window.Vitalis, h = React.createElement;
  ReactDOM.createRoot(document.getElementById('root')).render(
    h(V.VitalReadout, { label: 'Heart rate', value: 96, unit: 'bpm', tier: 'YELLOW', source: 'simulated' }));
</script>
```

## Connecting to the backend

All screens currently use hard-coded demo data defined at the top of each page's script (`CREW`, `ZONES`, `SCEN`). To go live, replace those arrays with data from the FastAPI backend (`backend/api`, port 8000). The tier and action strings already match `data/schemas/card.schema.json` and `verdict.schema.json`, and `source` values match `reading.schema.json`.

Thresholds and crew data are illustrative placeholders, not medical limits.
