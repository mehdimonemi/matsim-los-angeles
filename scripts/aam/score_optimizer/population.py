"""Population checkpoint helpers used only by score-optimizer experiments."""
from __future__ import annotations

import gzip
import math
import xml.etree.ElementTree as ET
from pathlib import Path


def is_genuine_aam_trip(row):
    return 'aam_drt' in row.get('modes','').split('-')


def operational_request_metrics(rows):
    requests=[row for row in rows if row.get('mode','aam_drt')=='aam_drt']
    completed=[row for row in requests if row.get('dropoff_s')]
    return dict(actualAamRequests=len(requests), actualAamBoardings=sum(bool(row.get('pickup_s')) for row in requests),
                completedAamRequests=len(completed), completedAamUsers=len({row['person'] for row in completed}),
                rejectedAamRequests=sum(row.get('rejected','').lower()=='true' for row in requests))

def routing_mode(leg: ET.Element) -> str | None:
    for attribute in leg.findall("./attributes/attribute"):
        if attribute.get("name") == "routingMode":
            return attribute.text
    return None


def set_routing_mode(leg: ET.Element, mode: str) -> None:
    attributes = leg.find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes"); leg.insert(0, attributes)
    attribute = next((item for item in attributes.findall("attribute")
                      if item.get("name") == "routingMode"), None)
    if attribute is None:
        attribute = ET.SubElement(attributes, "attribute",
                                  {"name": "routingMode", "class": "java.lang.String"})
    attribute.text = mode


def normalize_ground_routing_modes(elements: list[ET.Element]) -> None:
    legs = [element for element in elements if element.tag == "leg"]
    if not legs:
        return
    substantive = [leg.get("mode") for leg in legs if leg.get("mode") != "walk"]
    existing = [routing_mode(leg) for leg in legs if routing_mode(leg)]
    mode = "pt" if "pt" in substantive else (substantive[0] if substantive else
                                                (existing[0] if existing else "walk"))
    for leg in legs:
        set_routing_mode(leg, mode)


def is_aam_segment(elements: list[ET.Element]) -> bool:
    return any(element.tag == "leg" and
               element.get("mode") in ("aam", "aam_drt")
               for element in elements)


def is_main_activity(element: ET.Element) -> bool:
    return element.tag in ("act", "activity") and "interaction" not in element.get("type", "").lower()


def record_candidate(person, trip_index, origin, destination, segment, reason):
    attributes = person.find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes"); person.insert(0, attributes)
    name = f"aam_unresolved_{trip_index}"
    record = next((a for a in attributes if a.get("name") == name), None)
    if record is None:
        record = ET.SubElement(attributes, "attribute", {"name": name, "class": "java.lang.String"})
    departure = origin.get("end_time") or next((e.get("dep_time") for e in segment if e.tag == "leg" and e.get("dep_time")), "unknown")
    record.text = f"person={person.get('id')};trip={trip_index};origin={origin.attrib};destination={destination.attrib};departure={departure};reason={reason}"


def sanitize_population(source: Path, destination: Path, layout_id: str | None = None,
                        *, preserve_learning: bool = False, previous_layout_id: str | None = None) -> dict:
    """Clear every copied score and collapse layout-specific AAM stage chains."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    from scripts.aam_repair.checkpoints import archive_population
    archive_population(source, Path(str(destination) + ".observed-plans.jsonl"), layout_id)
    opener = gzip.open if source.suffix == ".gz" else open
    writer = (gzip.open(destination, "wt", encoding="utf-8") if destination.suffix == ".gz"
              else destination.open("w", encoding="utf-8"))
    people = plans = aam_plans = cleared = 0
    same_layout = preserve_learning and layout_id is not None and layout_id == previous_layout_id
    with opener(source, "rb") as stream, writer as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        out.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n<population>\n')
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            people += 1
            for plan in person.findall("plan"):
                plans += 1
                if same_layout:
                    continue
                physical_air=any(is_aam_segment([leg]) for leg in plan.findall('leg'))
                if preserve_learning and not physical_air:
                    continue
                if 'score' in plan.attrib:cleared += 1
                plan.attrib.pop("score", None)
                children = list(plan)
                main = [index for index, element in enumerate(children) if is_main_activity(element)]
                if len(main) < 2:
                    continue
                rebuilt = children[:main[0] + 1]
                changed = False
                for trip_index, (start, end) in enumerate(zip(main, main[1:])):
                    segment = children[start + 1:end]
                    if is_aam_segment(segment):
                        record_candidate(person, trip_index, children[start], children[end], segment, "layout_invalidated")
                        mode = "aam" if preserve_learning else "ride"
                        leg = ET.Element("leg", {"mode": mode}); set_routing_mode(leg, mode)
                        rebuilt.append(leg); changed = True
                    else:
                        if any(e.tag == "leg" and routing_mode(e) == "aam" for e in segment) or (plan.get("type") == "aam" and not any(leg.get("mode") in ("aam", "aam_drt") for leg in plan.findall("leg"))):
                            record_candidate(person, trip_index, children[start], children[end], segment, "ground_fallback")
                            mode = next((e.get("mode") for e in segment if e.tag == "leg" and e.get("mode") not in ("walk", "aam")), "ride")
                            segment = [ET.Element("leg", {"mode": mode})]
                        normalize_ground_routing_modes(segment); rebuilt.extend(segment)
                    rebuilt.append(children[end])
                rebuilt.extend(children[main[-1] + 1:])
                if changed:
                    aam_plans += 1; plan[:] = rebuilt
                    plan.set("type", "aam" if preserve_learning else "ground")
                    if preserve_learning:
                        attrs=plan.find('attributes')
                        if attrs is not None:
                            for attr in list(attrs):
                                if attr.get('name') in ('aam_park_vertiport','aam_private_route_infeasible'):
                                    attrs.remove(attr)
                else:
                    plan[:] = rebuilt
                    if plan.get("type") == "aam":
                        plan.set("type", "ground")
                if plan.get("type") == "ground":
                    attributes = plan.find("attributes")
                    if attributes is not None:
                        for attribute in list(attributes):
                            if attribute.get("name", "").startswith("aam_"):
                                attributes.remove(attribute)
            out.write(ET.tostring(person, encoding="unicode")); out.write("\n"); person.clear()
        out.write("</population>\n")
    return {"people": people, "plans": plans, "layoutInvalidatedAamPlans": aam_plans,
            "scoresCleared": cleared, "sameLayoutPreserved": same_layout,
            "learningPreserved": preserve_learning}


def best_aam_scores(path: Path) -> dict[str, float]:
    result = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            scores = []
            for plan in person.findall("plan"):
                is_aam = any(leg.get("mode") == "aam_drt" for leg in plan.findall("leg"))
                try:
                    score = float(plan.get("score", "nan"))
                except ValueError:
                    score = math.nan
                if is_aam and math.isfinite(score):
                    scores.append(score)
            if scores:
                result[person.get("id")] = max(scores)
            person.clear()
    return result


def population_score_metrics(path: Path) -> dict:
    """Summarize final system scores and actual selected-plan AAM adoption."""
    opener = gzip.open if path.suffix == ".gz" else open
    selected_scores, best_scores, selected_aam_scores = [], [], []
    scored_aam_users = selected_aam_users = marker_only_plans = ground_fallback_plans = 0
    with opener(path, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            person_scores, person_has_scored_aam = [], False
            selected_plan = None
            for plan in person.findall("plan"):
                try:
                    score = float(plan.get("score", "nan"))
                except ValueError:
                    score = math.nan
                is_aam = any(leg.get("mode") == "aam_drt" for leg in plan.findall("leg"))
                marker = plan.get("type") == "aam" or any(leg.get("mode") == "aam" or routing_mode(leg) == "aam" for leg in plan.findall("leg"))
                marker_only_plans += int(marker and not is_aam)
                ground_fallback_plans += int(not is_aam and ((marker and all(leg.get("mode") != "aam" for leg in plan.findall("leg"))) or plan.find("./attributes/attribute[@name='aam_ground_fallback']") is not None))
                if plan.get("selected") == "yes" and is_aam:
                    selected_aam_users += 1
                if math.isfinite(score):
                    person_scores.append(score)
                    person_has_scored_aam |= is_aam
                if plan.get("selected") == "yes":
                    selected_plan = (score, is_aam)
            if person_scores:
                best_scores.append(max(person_scores))
            if person_has_scored_aam:
                scored_aam_users += 1
            if selected_plan is not None and math.isfinite(selected_plan[0]):
                selected_scores.append(selected_plan[0])
                if selected_plan[1]:
                    selected_aam_scores.append(selected_plan[0])
            person.clear()

    def total(values: list[float]) -> float:
        return float(sum(values))

    def mean(values: list[float]) -> float | None:
        return float(sum(values) / len(values)) if values else None

    return {"scoredPopulation": len(selected_scores),
            "selectedPlanScoreSum": total(selected_scores),
            "selectedPlanScoreMean": mean(selected_scores),
            "bestPlanScoreSum": total(best_scores),
            "bestPlanScoreMean": mean(best_scores),
            "selectedAamUsers": selected_aam_users,
            "markerOnlyPlans": marker_only_plans,
            "groundFallbackPlans": ground_fallback_plans,
            "selectedAamScoreSum": total(selected_aam_scores),
            "selectedAamScoreMean": mean(selected_aam_scores),
            "scoredAamAlternativeUsers": scored_aam_users}
