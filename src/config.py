"""Configuration loaded from environment variables (see .env.example).

Nothing secret or site-specific is hard-coded here, so the repository is safe
to make public. Local runs read real values from a `.env` file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional; plain environment variables still work
    pass


# --- ALA (public API, no authentication required) ---------------------------
ALA_SEARCH_URL = "https://biocache-ws.ala.org.au/ws/occurrences/search"
ALA_PAGE_SIZE = 100        # ALA returns HTTP 503 for pageSize > ~100
ALA_MAX_WINDOW = 5000      # ALA caps a single query at 5000 records
ALA_START_YEAR = int(os.getenv("ALA_START_YEAR", "2000"))
RECENT_MONTHS = int(os.getenv("RECENT_MONTHS", "6"))

REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "20"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))
HEALTH_CHECK_TRIES = 5
HEALTH_CHECK_PASS = 3

# Fields we keep from each ALA record. We deliberately do NOT pass ALA's `fl`
# parameter, because ALA drops the `uuid` field whenever `fl` is used, which
# breaks de-duplication. We fetch full records and slim them in Python instead.
NEEDED_FIELDS = [
    "uuid", "scientificName", "vernacularName",
    "decimalLatitude", "decimalLongitude", "eventDate",
    "images", "classs", "stateConservation", "austConservation",
]

# Taxa we never want (open-ocean / marine species that stray into a bbox).
MARINE_BLACKLIST = ["Cerithium", "Thalassarche"]


# --- ArcGIS Online (only needed for main.py, not the demo) ------------------
@dataclass
class ArcGISConfig:
    username: str = os.getenv("ARCGIS_USERNAME", "")
    password: str = os.getenv("ARCGIS_PASSWORD", "")
    url: str = os.getenv("ARCGIS_URL", "https://www.arcgis.com")
    feature_layer_url: str = os.getenv("FEATURE_LAYER_URL", "")
    layer_title: str = os.getenv("LAYER_TITLE", "ALA_Species_Observations")
    output_csv: str = os.getenv("OUTPUT_CSV", "output/ala_species.csv")

    def require(self) -> None:
        missing = [k for k in ("username", "password", "feature_layer_url")
                   if not getattr(self, k)]
        if missing:
            raise SystemExit(
                "Missing required config: "
                + ", ".join(m.upper() for m in missing)
                + ". Copy .env.example to .env and fill it in."
            )
