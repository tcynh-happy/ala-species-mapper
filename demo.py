#!/usr/bin/env python3
"""Zero-configuration demo — no accounts, no API keys.

Fetches recent species occurrences from the public Atlas of Living Australia
API inside a sample public boundary (Royal National Park, NSW), filters them to
the polygon, and writes three artefacts to ``output/``:

    output/demo_species.csv      tabular data
    output/demo_species.geojson  GIS-ready points
    output/demo_map.html         interactive Leaflet map (open in a browser)

Run it:
    python demo.py
    python demo.py --months 12        # look back 12 months instead of 6
"""
from __future__ import annotations

import argparse
import logging
import os

from src import config, mapping
from src.ala_client import ALAClient, months_between
from src.geo import (drop_marine, filter_to_boundary, load_boundary,
                     records_to_dataframe)

BOUNDARY = os.path.join(os.path.dirname(__file__), "data", "demo_boundary.geojson")
OUT_DIR = "output"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ALA species mapper — zero-auth demo")
    ap.add_argument("--months", type=int, default=config.RECENT_MONTHS,
                    help="How many recent months to fetch (default 6).")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    boundary, bounds = load_boundary(BOUNDARY)

    client = ALAClient()
    if not client.is_healthy():
        logging.error("ALA is unstable right now — try again later.")
        return 1

    months = months_between(config.ALA_START_YEAR, args.months, full=False)
    records = client.fetch_months(months, bounds)

    df = records_to_dataframe(records)
    if df.empty:
        logging.warning("No records returned.")
        return 0
    df = filter_to_boundary(df, boundary)
    df = drop_marine(df)
    df = mapping.enrich(df)

    if df.empty:
        logging.warning("No records inside the boundary.")
        return 0

    mapping.to_csv(df, f"{OUT_DIR}/demo_species.csv")
    mapping.to_geojson(df, f"{OUT_DIR}/demo_species.geojson")
    mapping.build_map(df, boundary, f"{OUT_DIR}/demo_map.html",
                      title="Green Triangle — ALA species")

    print(f"\nDone. {len(df)} occurrences mapped.")
    print(f"Open {OUT_DIR}/demo_map.html in your browser.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
