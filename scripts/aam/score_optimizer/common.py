"""Self-contained candidate/layout I/O for the score optimizer package."""
from __future__ import annotations

import csv
import hashlib
import math
import os
import re
import tempfile
from pathlib import Path

import numpy as np

MILE = 1609.344


def read_sites(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    required = {"id", "x", "y"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"{path} must have columns id,name,x,y")
    result, seen = [], set()
    for row in rows:
        site_id = row["id"].strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", site_id) or site_id in seen:
            raise ValueError(f"invalid or duplicate candidate id: {site_id!r}")
        seen.add(site_id)
        name = row.get("name", site_id).strip() or site_id
        if "," in name:
            raise ValueError(f"candidate name may not contain a comma: {name!r}")
        x, y = float(row["x"]), float(row["y"])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"non-finite coordinates for {site_id}")
        result.append({"id": site_id, "name": name, "x": x, "y": y})
    return result


def distance_matrix(points: np.ndarray, sites: np.ndarray) -> np.ndarray:
    return np.hypot(points[:, None, 0] - sites[None, :, 0],
                    points[:, None, 1] - sites[None, :, 1])


def atomic_write_layout(path: Path, sites: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                              dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["id", "name", "x", "y"])
            writer.writeheader(); writer.writerows(sites)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return hashlib.sha256(path.read_bytes()).hexdigest()
