"""Immutable score provenance; a score belongs to an exact plan and layout."""
import gzip
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def archive_population(source, destination, layout_id=None):
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A legacy checkpoint may lack its layout identity. Do not fabricate one.
    provenance = {"source": str(source.resolve()), "layoutId": layout_id,
                  "layoutKnown": layout_id is not None}
    opener = gzip.open if source.suffix == ".gz" else open
    count = 0
    with opener(source, "rb") as stream, destination.open("x", encoding="utf-8") as out:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            for index, plan in enumerate(person.findall("plan")):
                xml = ET.tostring(plan, encoding="unicode")
                score = float(plan.get("score", "nan"))
                row = {**provenance, "person": person.get("id"), "planIndex": index,
                       "planHash": hashlib.sha256(xml.encode()).hexdigest(), "planXml": xml,
                       "observedScore": score if math.isfinite(score) else None,
                       "selected": plan.get("selected") == "yes"}
                out.write(json.dumps(row, allow_nan=False) + "\n")
                count += 1
            person.clear()
    return count
