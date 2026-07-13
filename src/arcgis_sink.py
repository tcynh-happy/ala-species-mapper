"""Optional sink: push occurrences to an ArcGIS Online Feature Layer.

Only used by ``main.py``. The demo does not import this module, so folium /
pandas users can try the project without installing the (heavier) arcgis SDK.
"""
from __future__ import annotations

import logging

import pandas as pd

from . import config

log = logging.getLogger(__name__)
UPLOAD_BATCH_SIZE = 500


def login(cfg: config.ArcGISConfig):
    """Log in once and return (GIS, token). Requires the arcgis SDK."""
    from arcgis.gis import GIS

    cfg.require()
    gis = GIS(url=cfg.url, username=cfg.username, password=cfg.password)
    token = gis._con.token
    log.info("ArcGIS login OK as %s", gis.properties.user.username)
    return gis, token


def load_boundary_geojson(feature_layer_url: str, token: str) -> dict:
    """Fetch the boundary polygons from an ArcGIS Feature Service as GeoJSON."""
    import requests

    r = requests.get(feature_layer_url, params={
        "where": "1=1", "outFields": "*", "outSR": "4326",
        "f": "geojson", "token": token,
    }, timeout=60)
    return r.json()


def _features(df: pd.DataFrame) -> list:
    from arcgis.features import Feature
    from arcgis.geometry import Point

    feats = []
    for _, row in df.iterrows():
        try:
            date_ms = int(pd.to_numeric(row.get("eventDate"), errors="coerce"))
        except (ValueError, TypeError):
            date_ms = None
        feats.append(Feature(
            geometry=Point({"x": float(row["decimalLongitude"]),
                            "y": float(row["decimalLatitude"]),
                            "spatialReference": {"wkid": 4326}}),
            attributes={
                "scientificName": str(row.get("scientificName", "")),
                "vernacularName": str(row.get("vernacularName", "")),
                "decimalLatitude": float(row.get("decimalLatitude", 0)),
                "decimalLongitude": float(row.get("decimalLongitude", 0)),
                "eventDate": date_ms,
                "dataSource": "ALA",
                "photoURL": str(row.get("photoURL", "")),
                "uuid": str(row.get("uuid", "")),
                "stateConservation": str(row.get("stateConservation", "")),
                "austConservation": str(row.get("austConservation", "")),
            },
        ))
    return feats


def push(gis, df: pd.DataFrame, cfg: config.ArcGISConfig, full: bool) -> None:
    """Update an existing Feature Layer, or create one from CSV if none exists."""
    items = gis.content.search(query=f"title:{cfg.layer_title}", item_type="Feature Service")
    if not items:
        log.info("No existing layer; creating one from %s", cfg.output_csv)
        item = gis.content.add(item_properties={
            "title": cfg.layer_title, "type": "CSV",
            "tags": "ALA, species, biodiversity",
            "description": "Species occurrence data from the Atlas of Living Australia",
        }, data=cfg.output_csv)
        published = item.publish(publish_parameters={
            "type": "csv", "locationType": "coordinates",
            "latitudeFieldName": "decimalLatitude",
            "longitudeFieldName": "decimalLongitude",
            "coordinateFieldType": "LatLong",
        })
        log.info("New Feature Layer created: %s", published.url)
        return

    layer = items[0].layers[0]
    if full:
        layer.delete_features(where="1=1")
        to_add = df
        log.info("Full update: cleared existing records")
    else:
        try:
            existing = layer.query(where="1=1", out_fields=["uuid"]).sdf
            ids = set(existing["uuid"].dropna().astype(str))
            to_add = df[~df["uuid"].astype(str).isin(ids)]
            log.info("New records: %d (skipped %d duplicates)", len(to_add), len(df) - len(to_add))
        except Exception as e:  # noqa: BLE001 - arcgis raises varied errors
            to_add = df
            log.warning("Duplicate check failed (%s); adding all", e)

    if to_add.empty:
        log.info("Layer already up to date")
        return

    feats = _features(to_add)
    for i in range(0, len(feats), UPLOAD_BATCH_SIZE):
        layer.edit_features(adds=feats[i:i + UPLOAD_BATCH_SIZE])
        log.info("Uploaded %d/%d", min(i + UPLOAD_BATCH_SIZE, len(feats)), len(feats))
    log.info("Added %d records", len(feats))
