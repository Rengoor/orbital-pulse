# NASA data sources

| Source | Drives | Access | Fallback | Status |
|---|---|---|---|---|
| OSDR, Inspiration4 blood studies (OSD-569, -570, -571, -575) | Personal baselines (pre-flight draws L-92, L-44, L-3) | OSDR portal / API | Website download | not tested |
| RadLab (ISS modules, Artemis I telemetry) | Radiation channel, exposure ledger | Portal / Data API | Artemis I paper source-data spreadsheets | not tested |
| DONKI (free key at api.nasa.gov; DEMO_KEY: 30 requests/hour) | Storm Day event window | REST API | One JSON response saved by hand | not tested |

Record dataset IDs, field names and timestamps here: they feed the provenance on every decision card.
