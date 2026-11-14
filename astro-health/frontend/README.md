# frontend/

**Owner:** person C

Streamlit app. Screens are named after the challenge verbs: Gather, Evaluate, Act. One file per page, so pages never collide.

## Rules for this folder

- Talk to the backend over HTTP only (`BACKEND_URL`). Never import backend code.
- `MOCK_MODE=1` reads `../data/fixtures/` so the UI works before the backend exists.
- Every screen shows the real/simulated label for its data.
- Status and one action come first; details on demand.
- Colour is never the only signal (icon and text too); GREY means insufficient data.
