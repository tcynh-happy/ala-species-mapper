"""Geometry helpers built on Shapely only (no GeoPandas dependency).

Dropping GeoPandas keeps installation painless — ``pip install shapely`` alone
works on every platform, whereas GeoPandas drags in GDAL/GEOS/PROJ that often
fail to build on Windows. Point-in-polygon tests use a prepared geometry so
filtering thousands of points stays fast.
"""
from __future__ import annotations

import json
import logging

import pandas as pd
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.prepared import prep

from . import config

log = logging.getLogger(__name__)

Bounds = tuple[float, float, float, float]


def load_boundary(geojson_path: str):
    """Load a GeoJSON FeatureCollection and return (merged_geometry, bounds)."""
    with open(geojson_path, "r", encoding="utf-8") as fh:
        gj = json.load(fh)
    geoms = [shape(f["geometry"]) for f in gj["features"]]
    merged = unary_union(geoms)
    log.info("Boundary loaded: %d feature(s)", len(geoms))
    return merged, merged.bounds


def boundary_from_arcgis_geojson(geojson: dict):
    """Same as load_boundary but for an already-parsed ArcGIS GeoJSON response."""
    geoms = [shape(f["geometry"]) for f in geojson["features"]]
    merged = unary_union(geoms)
    return merged, merged.bounds


def records_to_dataframe(records: list) -> pd.DataFrame:
    """Turn raw ALA records into a clean DataFrame: dedup + numeric coordinates."""
    df = pd.DataFrame(records)
    if df.empty:
        return df
    if "uuid" in df.columns:
        before = len(df)
        df = df[df["uuid"].astype(str) != ""].drop_duplicates(subset="uuid", keep="first")
        if before != len(df):
            log.info("Removed %d duplicate/blank uuids", before - len(df))
    df["decimalLatitude"] = pd.to_numeric(df["decimalLatitude"], errors="coerce")
    df["decimalLongitude"] = pd.to_numeric(df["decimalLongitude"], errors="coerce")
    df = df.dropna(subset=["decimalLatitude", "decimalLongitude"])
    return df.reset_index(drop=True)


def filter_to_boundary(df: pd.DataFrame, geometry) -> pd.DataFrame:
    """Keep only rows whose point falls inside the boundary geometry."""
    if df.empty:
        return df
    prepared = prep(geometry)
    mask = [
        prepared.contains(Point(lon, lat))
        for lon, lat in zip(df["decimalLongitude"], df["decimalLatitude"])
    ]
    out = df[mask].reset_index(drop=True)
    log.info("Within boundary: %d / %d", len(out), len(df))
    return out


def drop_marine(df: pd.DataFrame) -> pd.DataFrame:
    """Remove blacklisted marine taxa by scientific name substring."""
    if df.empty or "scientificName" not in df.columns:
        return df
    mask = ~df["scientificName"].str.contains(
        "|".join(config.MARINE_BLACKLIST), case=False, na=False
    )
    removed = len(df) - int(mask.sum())
    if removed:
        log.info("Marine filter removed %d rows", removed)
    return df[mask].reset_index(drop=True)
