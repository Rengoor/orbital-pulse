# validation/: REAL NASA data

> **Everything in this folder is real NASA data.** Nothing here is simulated, synthetic or
> altered. The unit tests in `backend/tests`, `data/tests` and `evidence/tests` use simulated
> data; this folder is where the decision system meets real measurements.

| Path | What it is |
|---|---|
| `fetch.py` | Downloads the data from NASA (`python -m validation.fetch`) |
| `data/` | The committed snapshot: values exactly as NASA returned them, plus `manifest.json` with each source URL, query, fetch time and SHA-256 |
| `run.py` | Runs every real measurement through the real decision system (`python -m validation.run`) |
| `results/validation.md` | The report (and `validation.json` with the raw numbers) |
| `tests/` | Pins the snapshot (checksums, labels, provenance) and checks the report still matches it |

## Data sources

| File | Source | What it is |
|---|---|---|
| `data/altea_dose_equivalent.csv` | NASA OSDR RadLab Data API, instrument ALTEA on the ISS | Dose-equivalent rate in µSv/h (the unit of the backend's dose channel), one sample per minute, 1–8 November 2010, with the ISS's latitude and longitude |
| `data/donki_sep.json` | NASA CCMC DONKI | Solar energetic particle events catalogued in the same week (there were none) |
| `data/inspiration4_glucose.json` | NASA OSDR OSD-575 (SpaceX Inspiration4, metabolic panel) | Glucose for all four crew at seven draws, with the laboratory's own reference range |

Only ALTEA reports `dose_equivalent_rate` in RadLab. As of 2026-11-15, DosTel, TEPC,
IV-TEPC, RAD, Lidal, REM and Liulin-5 return no values for it, and ALTEA's public data
covers 2010–2011. That is why the window is in 2010.

## What it shows (full report: `results/validation.md`)

- **Radiation.** In a week with no solar storm, the project's placeholder dose-rate limits
  flag **31% of ISS samples**. The rate climbs from 5% near the equator to 63% at the ISS's
  highest latitudes, where Earth's magnetic field shields less. An instantaneous dose-rate
  alarm is not fit for crew use as it stands; it needs an orbit-aware or time-averaged rule.
- **Glucose.** On the 28 Inspiration4 draws, the system's verdict agrees with the laboratory's
  reference range on **24**. Two in-range values were flagged and two mildly high values
  (100 and 103 mg/dL) were not.

The limits being judged are the project's placeholders (`backend/pipelines/b_limits/limits_table.yaml`).
This validates how they behave on real data; it is not a clinical validation.

## Run

```bash
backend/.venv/bin/python -m validation.fetch    # optional: re-download from NASA
backend/.venv/bin/python -m validation.run      # about a minute; writes results/
backend/.venv/bin/python -m pytest validation/tests -q
```
