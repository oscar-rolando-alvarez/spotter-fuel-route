"""Loads the US boundary (Census cartographic boundary, 1:5M) into a domain Region (ADR-0014)."""

import gzip
import json
from functools import lru_cache
from pathlib import Path

from fuel_route.domain.geo import Region


@lru_cache(maxsize=4)
def load_region(path: Path) -> Region:
    return Region(json.loads(gzip.decompress(path.read_bytes())))
