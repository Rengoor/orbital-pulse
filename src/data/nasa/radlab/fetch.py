"""Pull RadLab dose rates.

Source: NASA OSDR RadLab Data API (https://visualization.osdr.nasa.gov/radlab/api).
Pulls every instrument reporting an absorbed dose rate in a time window and
reduces it to hourly statistics per instrument. The default window is the May
2024 solar storm, when instruments on the ISS, in lunar orbit, in deep space
and on the surface of Mars were all recording.

UNIT: the RadLab Data API documentation
(https://visualization.osdr.nasa.gov/radlab/gui/data-api, checked 2026-11-14)
states ``absorbed_dose_rate`` is in uGy/hour, which matches the magnitudes
seen here. The API also offers a separate ``dose_equivalent_rate`` field in
uSv/hour where available; fetching that field directly is the sanctioned
route if radiation is ever to reach the decision pipelines. Never convert
absorbed dose to dose equivalent with an assumed quality factor.

Original caveat (kept for the record): the API returns the value as a bare
number. Values
are consistent with micrograys per hour (quiet ISS 4-7, Mars surface ~6, deep
space ~8), and that is how they are labelled here, but the unit was inferred
and not read from RadLab documentation. This is an absorbed dose (Gy), not a
dose equivalent (Sv): it must not be fed to the dose_rate_usv_h channel or
compared with a sievert limit without a quality factor.

    python -m data.nasa.radlab.fetch [--start 2024-05-08T00:00] [--end 2024-05-14T00:00]

Owner: person D
"""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

from data.nasa.common import download, utc_now, write_processed

API_URL = "https://visualization.osdr.nasa.gov/radlab/api/"
PROCESSED_DIR = Path(__file__).resolve().parent / "processed"
DOSE_RATES_PATH = PROCESSED_DIR / "dose_rates.json"

DEFAULT_START = "2024-05-08T00:00"
DEFAULT_END = "2024-05-14T00:00"

# Where each vehicle was, in words a reviewer can check.
LOCATIONS = {
    "ISS": "low Earth orbit",
    "LRO": "lunar orbit",
    "BioSentinel": "deep space (heliocentric orbit)",
    "Curiosity": "Mars surface (Gale crater)",
}


def fetch(start: str = DEFAULT_START, end: str = DEFAULT_END) -> dict:
    """Download the window and write processed/dose_rates.json."""
    body = download(
        API_URL,
        f"radlab_{start[:10]}_{end[:10]}.csv",
        params=[
            (f"timestamp>={start}", None),
            (f"timestamp<{end}", None),
            ("absorbed_dose_rate", None),
            ("instrument", None),
            ("module", None),
            ("spacecraft", None),
            ("format", "csv"),
        ],
        timeout=300.0,
    )

    hourly: dict[tuple, dict[str, list[float]]] = {}
    for row in csv.DictReader(io.StringIO(body.decode("utf-8"))):
        try:
            value = float(row["absorbed_dose_rate"])
        except (TypeError, ValueError):
            continue
        key = (row["spacecraft"], row["instrument"], row.get("module") or "")
        hourly.setdefault(key, {}).setdefault(row["timestamp"][:13], []).append(value)

    series = []
    for (spacecraft, instrument, module), hours in sorted(hourly.items()):
        points = [
            {
                "hour": f"{hour}:00Z",
                "mean": round(sum(values) / len(values), 4),
                "max": round(max(values), 4),
                "n": len(values),
            }
            for hour, values in sorted(hours.items())
        ]
        every = [v for values in hours.values() for v in values]
        series.append(
            {
                "spacecraft": spacecraft,
                "location": LOCATIONS.get(spacecraft, "unknown"),
                "instrument": instrument,
                "module": module or None,
                "samples": len(every),
                "window_mean": round(sum(every) / len(every), 4),
                "window_max": round(max(every), 4),
                "peak_hour": max(points, key=lambda p: p["max"])["hour"],
                "hourly": points,
            }
        )

    payload = {
        "source": "NASA OSDR RadLab Data API",
        "url": API_URL,
        "dataset_id": "RadLab",
        "field": "absorbed_dose_rate",
        "unit": "uGy/h",
        "unit_note": "uGy/hour per the RadLab Data API documentation (visualization.osdr.nasa.gov/radlab/gui/data-api, checked 2026-11-14). Absorbed dose, not dose equivalent.",
        "fetched_at": utc_now(),
        "window": {"start": start + "Z", "end": end + "Z"},
        "series": series,
    }
    write_processed(DOSE_RATES_PATH, payload)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    args = parser.parse_args()
    result = fetch(args.start, args.end)
    for s in result["series"]:
        print(f"{s['spacecraft']:12} {s['instrument']:9} {s['samples']:6} samples  mean {s['window_mean']:9.3f}  max {s['window_max']:9.3f}  peak {s['peak_hour']}")
    print(f"-> {DOSE_RATES_PATH}")
