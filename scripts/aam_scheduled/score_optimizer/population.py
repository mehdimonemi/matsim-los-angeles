"""MATSim population helpers for staged scheduled-AAM experiments."""
from __future__ import annotations

import gzip
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

PREFIX = "aam_sched_"
ROUTING_MODE = "scheduled_aam"


def _open(path: Path, mode: str):
    if "b" in mode:
        return gzip.open(path, mode) if path.suffix == ".gz" else path.open(mode)
    return gzip.open(path, mode, encoding="utf-8") if path.suffix == ".gz" else path.open(mode, encoding="utf-8")


def routing_mode(leg: ET.Element) -> str | None:
    for attribute in leg.findall("./attributes/attribute"):
        if attribute.get("name") == "routingMode":
            return attribute.text
    return None


def route_data(leg: ET.Element) -> dict:
    route = leg.find("route")
    text = (route.text or "").strip() if route is not None else ""
    if route is not None and route.get("type") == "default_pt" and text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
    return {}


def is_scheduled_aam_leg(leg: ET.Element) -> bool:
    line = route_data(leg).get("transitLineId", "")
    return (line.startswith(PREFIX + "line_") or routing_mode(leg) == ROUTING_MODE
            or leg.get("mode") == ROUTING_MODE)


def is_main_activity(element: ET.Element) -> bool:
    return element.tag in ("act", "activity") and "interaction" not in element.get("type", "").lower()


def _set_routing_mode(leg: ET.Element, mode: str) -> None:
    attributes = leg.find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes")
        leg.insert(0, attributes)
    value = next((item for item in attributes.findall("attribute") if item.get("name") == "routingMode"), None)
    if value is None:
        value = ET.SubElement(attributes, "attribute", {"name": "routingMode", "class": "java.lang.String"})
    value.text = mode


def _normalize_ground(elements: list[ET.Element]) -> None:
    legs = [element for element in elements if element.tag == "leg"]
    substantive = [leg.get("mode") for leg in legs if leg.get("mode") not in (None, "walk")]
    mode = "pt" if "pt" in substantive else (substantive[0] if substantive else "walk")
    for leg in legs:
        _set_routing_mode(leg, mode)


def sanitize_population(source: Path, destination: Path, layout_id: str | None = None) -> dict:
    """Clear scores and replace layout-specific scheduled-AAM chains by one request leg."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    from scripts.aam_repair.checkpoints import archive_population
    archive_population(source, Path(str(destination) + ".observed-plans.jsonl"), layout_id)
    people = plans = aam_plans = 0
    with _open(source, "rb") as stream, _open(destination, "wt") as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        out.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n<population>\n')
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            people += 1
            for plan in person.findall("plan"):
                plans += 1
                plan.attrib.pop("score", None)
                children = list(plan)
                main = [index for index, element in enumerate(children) if is_main_activity(element)]
                if len(main) < 2:
                    continue
                rebuilt = children[:main[0] + 1]
                changed = False
                for start, end in zip(main, main[1:]):
                    segment = children[start + 1:end]
                    if any(element.tag == "leg" and is_scheduled_aam_leg(element) for element in segment):
                        request = ET.Element("leg", {"mode": ROUTING_MODE})
                        _set_routing_mode(request, ROUTING_MODE)
                        rebuilt.append(request)
                        changed = True
                    else:
                        _normalize_ground(segment)
                        rebuilt.extend(segment)
                    rebuilt.append(children[end])
                rebuilt.extend(children[main[-1] + 1:])
                if changed:
                    aam_plans += 1
                    plan[:] = rebuilt
            out.write(ET.tostring(person, encoding="unicode") + "\n")
            person.clear()
        out.write("</population>\n")
    return {"people": people, "plans": plans, "layoutInvalidatedAamPlans": aam_plans, "scoresCleared": plans}


def plan_is_aam(plan: ET.Element) -> bool:
    return any(is_scheduled_aam_leg(leg) for leg in plan.findall("leg"))


def best_aam_scores(path: Path) -> dict[str, float]:
    result = {}
    with _open(path, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            scores = []
            for plan in person.findall("plan"):
                try:
                    score = float(plan.get("score", "nan"))
                except ValueError:
                    score = math.nan
                if plan_is_aam(plan) and math.isfinite(score):
                    scores.append(score)
            if scores:
                result[person.get("id")] = max(scores)
            person.clear()
    return result


def population_score_metrics(path: Path) -> dict:
    selected, best, selected_aam = [], [], []
    scored_aam = 0
    with _open(path, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            person_scores, chosen, has_aam = [], None, False
            for plan in person.findall("plan"):
                try:
                    score = float(plan.get("score", "nan"))
                except ValueError:
                    score = math.nan
                aam = plan_is_aam(plan)
                if math.isfinite(score):
                    person_scores.append(score)
                    has_aam |= aam
                if plan.get("selected") == "yes":
                    chosen = (score, aam)
            if person_scores:
                best.append(max(person_scores))
            scored_aam += int(has_aam)
            if chosen and math.isfinite(chosen[0]):
                selected.append(chosen[0])
                if chosen[1]:
                    selected_aam.append(chosen[0])
            person.clear()
    mean = lambda values: float(sum(values) / len(values)) if values else None
    return {"scoredPopulation": len(selected), "selectedPlanScoreSum": float(sum(selected)),
            "selectedPlanScoreMean": mean(selected), "bestPlanScoreSum": float(sum(best)),
            "bestPlanScoreMean": mean(best), "selectedAamUsers": len(selected_aam),
            "selectedAamScoreSum": float(sum(selected_aam)), "selectedAamScoreMean": mean(selected_aam),
            "scoredAamAlternativeUsers": scored_aam}
