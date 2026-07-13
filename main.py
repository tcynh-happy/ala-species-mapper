#!/usr/bin/env python3
"""Full pipeline: ALA occurrences -> filter to a private boundary -> ArcGIS Online.

Unlike demo.py, this needs ArcGIS Online credentials and a Feature Service URL
(all read from a local .env file — nothing sensitive lives in the repo).

    python main.py                 # weekly update: recent months, append new
    python main.py --full          # full re-fetch and replace everything
"""
from __future__ import annotations

import argparse
import logging

from src import config, mapping
from src.ala_client import ALAClient, months_between
from src.arcgis_sink import load_boundary_geojson, login, push
from src.geo import (boundary_from_arcgis_geojson, drop_marine,
                     filter_to_boundary, records_to_dataframe)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ALA -> ArcGIS Online pipeline")
    ap.add_argument("--full", action="store_true",
                    help="Full re-fetch from ALA_START_YEAR and replace all data.")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    cfg = config.ArcGISConfig()
    cfg.require()

    client = ALAClient()
    if not client.is_healthy():
        logging.error("ALA is unstable right now — try again later.")
        return 1

    gis, token = login(cfg)
    boundary_gj = load_boundary_geojson(cfg.feature_layer_url, token)
    boundary, bounds = boundary_from_arcgis_geojson(boundary_gj)

    months = months_between(config.ALA_START_YEAR, config.RECENT_MONTHS, full=args.full)
    records = client.fetch_months(months, bounds)

    df = records_to_dataframe(records)
    df = filter_to_boundary(df, boundary)
    df = drop_marine(df)
    df = mapping.enrich(df)
    if df.empty:
        logging.warning("Nothing to upload.")
        return 0

    mapping.to_csv(df, cfg.output_csv)
    push(gis, df, cfg, full=args.full)

    logging.info("Done — mode: %s", "full" if args.full else "weekly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
