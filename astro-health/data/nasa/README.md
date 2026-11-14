# NASA data sources

All three are fetched live from NASA and reduced to small processed files that
are committed. Raw downloads go to `raw/` (git-ignored).

| Source | Datasets | What we take | Used for | Fetch | Status |
|---|---|---|---|---|---|
| OSDR, SpaceX Inspiration4 | OSD-569 (CBC), OSD-575 (CMP) | 4 crew, 7 draws each (L-92, L-44, L-3, R+1, R+45, R+82, R+194), with the laboratory reference range per analyte | Personal baselines for pipeline A (pre-flight glucose); blood panels for clinicians | `python -m data.nasa.osdr_inspiration4.fetch` then `...build_baselines` | tested 2026-11-14 |
| OSDR RadLab Data API | RadLab | `absorbed_dose_rate` per instrument, hourly mean/max: ISS (DosTel1, DosTel2), LRO (CRaTER), BioSentinel (BPD), Curiosity (MSL-RAD) | Radiation context in the views | `python -m data.nasa.radlab.fetch` | tested 2026-11-14 |
| CCMC DONKI | DONKI | Flares, solar energetic particle events, geomagnetic storms, CMEs | Event timeline | `python -m data.nasa.donki.fetch` | tested 2026-11-14 |

Default window for RadLab and DONKI: 2024-05-08 to 2024-05-14, the May 2024 storm.

## Things to know

- **RadLab unit.** The API returns a bare number. It is labelled uGy/h because
  the magnitudes fit (quiet ISS 4-7, Mars surface about 6), but that was
  inferred, not read from RadLab documentation. It is an absorbed dose (Gy),
  not a dose equivalent (Sv), so it is **not** fed to the `dose_rate_usv_h`
  channel or compared with the pipeline's dose limits.
- **Blood ranges.** `range_min` / `range_max` are the laboratory reference
  ranges published in the datasets. They are not project thresholds and not
  NASA medical limits.
- **Baselines.** Only glucose maps onto a reading channel today, so only
  glucose has a personal baseline. Three pre-flight draws is a small baseline;
  pipeline A treats it as low confidence.
- **DONKI host.** The fetcher uses `ccmc.gsfc.nasa.gov`, which needs no key.
  `api.nasa.gov` with `DEMO_KEY` is limited to 30 requests an hour per network
  and was exhausted on the test network. Set `NASA_API_KEY` to use it.
- **Provenance.** Every processed file records its source, dataset, field and
  fetch time; the `/nasa/*` backend routes pass these through.
