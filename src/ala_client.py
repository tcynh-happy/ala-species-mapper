"""Client for the Atlas of Living Australia (ALA) occurrence API.

The ALA biocache API is public and needs no authentication, which is what makes
the demo in this repo runnable by anyone.

Design notes
------------
* A single ``requests.Session`` is reused for connection pooling.
* Queries are made per-month; any month that exceeds ALA's 5000-record cap is
  split in half recursively (binary date-range splitting) until each slice fits.
* We never send ALA's ``fl`` parameter (it silently drops ``uuid``), so records
  come back in full and are slimmed in Python — de-duplication by ``uuid`` then
  actually works.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

import requests

from . import config

log = logging.getLogger(__name__)

Bounds = tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)


class ALAClient:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "ala-species-mapper/1.0"})

    # -- health -------------------------------------------------------------
    def is_healthy(self) -> bool:
        """Ping ALA a few times; True if enough pings succeed to be worth starting."""
        log.info("Checking ALA server health...")
        ok = 0
        for i in range(config.HEALTH_CHECK_TRIES):
            try:
                r = self.session.get(
                    config.ALA_SEARCH_URL,
                    params={"q": "*:*", "pageSize": 1},
                    timeout=30,
                )
                if r.status_code == 200:
                    r.json()
                    ok += 1
                    log.info("  ping %d/%d: OK", i + 1, config.HEALTH_CHECK_TRIES)
                else:
                    log.info("  ping %d/%d: HTTP %s", i + 1, config.HEALTH_CHECK_TRIES, r.status_code)
                if ok >= config.HEALTH_CHECK_PASS:  # early exit once we've passed
                    break
            except requests.RequestException:
                log.info("  ping %d/%d: failed", i + 1, config.HEALTH_CHECK_TRIES)
            time.sleep(1)
        healthy = ok >= config.HEALTH_CHECK_PASS
        log.info("ALA health: %s (%d ok)", "GREEN" if healthy else "RED", ok)
        return healthy

    # -- fetching -----------------------------------------------------------
    @staticmethod
    def _slim(occ: dict) -> dict:
        return {f: occ.get(f, "") for f in config.NEEDED_FIELDS}

    def _fetch_page(self, params: dict) -> dict | None:
        for attempt in range(config.MAX_RETRIES):
            try:
                r = self.session.get(config.ALA_SEARCH_URL, params=params, timeout=60)
                return r.json()
            except requests.RequestException:
                if attempt < config.MAX_RETRIES - 1:
                    log.info("    retry %d/%d...", attempt + 1, config.MAX_RETRIES)
                    time.sleep(config.RETRY_DELAY)
        log.warning("    giving up after %d attempts", config.MAX_RETRIES)
        return None

    def fetch_range(self, start: str, end: str, bounds: Bounds) -> tuple[list, int]:
        """Fetch all records in [start, end) inside bounds. Returns (records, total)."""
        min_lon, min_lat, max_lon, max_lat = bounds
        records: list = []
        start_index = 0
        total = 0
        while True:
            data = self._fetch_page({
                "q": "*:*",
                "fq": [
                    f"longitude:[{min_lon} TO {max_lon}]",
                    f"latitude:[{min_lat} TO {max_lat}]",
                    f"eventDate:[{start}T00:00:00Z TO {end}T00:00:00Z]",
                ],
                "pageSize": config.ALA_PAGE_SIZE,
                "startIndex": start_index,
            })
            if data is None:
                break
            batch = data.get("occurrences", [])
            total = data.get("totalRecords", 0)
            if not batch:
                break
            records.extend(self._slim(o) for o in batch)
            if len(records) >= total or len(records) >= config.ALA_MAX_WINDOW:
                break
            start_index += config.ALA_PAGE_SIZE
            time.sleep(config.REQUEST_DELAY)
        return records, total

    def fetch_smart(self, start: str, end: str, bounds: Bounds, depth: int = 0) -> list:
        """Fetch a date range, splitting in half only when it exceeds ALA's cap."""
        recs, total = self.fetch_range(start, end, bounds)
        pad = "  " * depth
        if total <= config.ALA_MAX_WINDOW:
            if recs:
                log.info("%s%s..%s: %d/%d", pad, start, end, len(recs), total)
            return recs
        log.info("%s%s..%s: %d records — splitting", pad, start, end, total)
        d1, d2 = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d")
        mid = (d1 + (d2 - d1) / 2).strftime("%Y-%m-%d")
        if mid in (start, end):  # single day already over the cap; keep what we have
            return recs
        return self.fetch_smart(start, mid, bounds, depth + 1) + \
            self.fetch_smart(mid, end, bounds, depth + 1)

    def fetch_months(self, months: list[tuple[int, int]], bounds: Bounds) -> list:
        """Fetch a list of (year, month) tuples and return the combined records."""
        out: list = []
        for year, month in months:
            start = f"{year}-{month:02d}-01"
            end = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"
            recs = self.fetch_smart(start, end, bounds)
            if recs:
                out.extend(recs)
                log.info("%d-%02d done: +%d (total %d)", year, month, len(recs), len(out))
            time.sleep(config.REQUEST_DELAY)
        return out


def months_between(start_year: int, recent_months: int, full: bool) -> list[tuple[int, int]]:
    """Build the list of (year, month) tuples to fetch for full or recent mode."""
    now = datetime.now()
    months: list[tuple[int, int]] = []
    if full:
        for y in range(start_year, now.year + 1):
            for m in range(1, 13):
                if y == now.year and m > now.month:
                    break
                months.append((y, m))
    else:
        y, m = now.year, now.month
        for _ in range(recent_months):
            months.append((y, m))
            m -= 1
            if m == 0:
                m, y = 12, y - 1
        months.reverse()
    return months
