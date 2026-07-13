"""Turn a DataFrame of occurrences into portable outputs: CSV, GeoJSON, and an
interactive Leaflet map (via Folium) that opens in any browser.
"""
from __future__ import annotations

import json
import logging
import os

import pandas as pd

from . import config

log = logging.getLogger(__name__)

# Colour per high-level taxon class, for map markers and legend.
GROUP_COLOURS = {
    "Aves": "#2166ac",          # birds
    "Mammalia": "#8c510a",      # mammals
    "Reptilia": "#01665e",      # reptiles
    "Amphibia": "#5aae61",      # amphibians
    "Plantae": "#1b7837",       # plants
    "Magnoliopsida": "#1b7837",
    "Insecta": "#d6604d",       # insects
}
DEFAULT_COLOUR = "#762a83"


def _colour_for(taxon_class: str) -> str:
    return GROUP_COLOURS.get(str(taxon_class), DEFAULT_COLOUR)


def photo_url(images_val) -> str:
    """Build an ALA thumbnail URL from an occurrence's images list."""
    try:
        if isinstance(images_val, list) and images_val:
            return f"https://images.ala.org.au/image/proxyImageThumbnail?imageId={images_val[0]}"
    except (TypeError, IndexError):
        pass
    return ""


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add photoURL + a display date and normalise conservation columns."""
    if df.empty:
        return df
    df = df.copy()
    df["photoURL"] = df["images"].apply(photo_url) if "images" in df.columns else ""
    for col in ("stateConservation", "austConservation", "vernacularName", "classs"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)
    df["eventDateDisplay"] = pd.to_datetime(
        df.get("eventDate"), unit="ms", origin="unix", errors="coerce"
    ).dt.strftime("%d/%m/%Y")
    return df


def to_csv(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df.to_csv(path, index=False)
    log.info("CSV written: %s (%d rows)", path, len(df))


def to_geojson(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    features = []
    for _, r in df.iterrows():
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [float(r["decimalLongitude"]),
                                         float(r["decimalLatitude"])]},
            "properties": {
                "scientificName": r.get("scientificName", ""),
                "vernacularName": r.get("vernacularName", ""),
                "class": r.get("classs", ""),
                "eventDate": r.get("eventDateDisplay", ""),
                "stateConservation": r.get("stateConservation", ""),
                "austConservation": r.get("austConservation", ""),
                "photoURL": r.get("photoURL", ""),
            },
        })
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh)
    log.info("GeoJSON written: %s (%d features)", path, len(features))


def build_map(df: pd.DataFrame, boundary_geom, path: str, title: str = "ALA species") -> None:
    """Render an interactive Folium map with the boundary and coloured markers."""
    import folium  # imported here so the rest of the package works without folium

    minx, miny, maxx, maxy = boundary_geom.bounds
    center = [(miny + maxy) / 2, (minx + maxx) / 2]
    fmap = folium.Map(location=center, zoom_start=12, tiles="CartoDB positron")

    folium.GeoJson(
        boundary_geom.__geo_interface__,
        name="Boundary",
        style_function=lambda _: {"color": "#333", "weight": 2,
                                  "fillColor": "#999", "fillOpacity": 0.08},
    ).add_to(fmap)

    for _, r in df.iterrows():
        colour = _colour_for(r.get("classs", ""))
        photo = r.get("photoURL", "")
        img = f'<br><img src="{photo}" width="150">' if photo else ""
        popup = folium.Popup(
            f"<b><i>{r.get('scientificName','')}</i></b><br>"
            f"{r.get('vernacularName','')}<br>"
            f"{r.get('eventDateDisplay','')}{img}",
            max_width=200,
        )
        folium.CircleMarker(
            location=[float(r["decimalLatitude"]), float(r["decimalLongitude"])],
            radius=4, color=colour, fill=True, fill_color=colour, fill_opacity=0.8,
            popup=popup,
        ).add_to(fmap)

    _add_legend(fmap, df, title)
    folium.LayerControl().add_to(fmap)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fmap.save(path)
    log.info("Map written: %s", path)


def _add_legend(fmap, df: pd.DataFrame, title: str) -> None:
    import folium

    classes = [c for c in df.get("classs", pd.Series(dtype=str)).unique() if str(c)]
    rows = "".join(
        f'<div><span style="background:{_colour_for(c)};width:10px;height:10px;'
        f'display:inline-block;border-radius:50%;margin-right:6px;"></span>{c}</div>'
        for c in sorted(classes)
    )
    html = (
        f'<div style="position:fixed;bottom:24px;left:24px;z-index:9999;'
        f'background:white;padding:10px 12px;border:1px solid #ccc;border-radius:6px;'
        f'font:12px/1.5 sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.2);">'
        f'<b>{title}</b><br><small>{len(df)} occurrences</small><hr style="margin:6px 0">'
        f'{rows}</div>'
    )
    fmap.get_root().html.add_child(folium.Element(html))
