#!/usr/bin/env python3
import gzip
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from run_adaptive_vertiport_optimization import (compare_aam_score_sums,
                                                  evaluate_candidate,
                                                  sanitize_population)


def write(path: Path, aam_score: float, other_score: float, extra_aam: bool = False) -> None:
    xml = f'''<?xml version="1.0"?><population><person id="p1"><plan selected="yes" type="aam" score="{aam_score}">
    <activity type="home" x="0" y="0"/><leg mode="walk"><attributes><attribute name="routingMode" class="java.lang.String">aam</attribute></attributes><route type="generic" start_link="r" end_link="aam_loop_OLD"/></leg>
    <activity type="aam interaction" link="aam_loop_OLD"/><leg mode="aam_drt"><route type="drt" start_link="aam_loop_OLD" end_link="aam_loop_VP02"/></leg>
    <activity type="aam interaction" link="aam_loop_VP02"/><leg mode="walk"/><activity type="work" x="10000" y="0"/></plan>
    <plan selected="no" score="{other_score}"><activity type="home" x="0" y="0"/><leg mode="car"/><activity type="work" x="10000" y="0"/></plan></person>
    <person id="p2"><plan selected="yes" score="1"{(' type="aam"' if extra_aam else '')}><activity type="home" x="0" y="0"/>
    <leg mode="walk"><attributes><attribute name="routingMode" class="java.lang.String">car</attribute></attributes></leg>
    <activity type="car interaction"/><leg mode="ride"><attributes><attribute name="routingMode" class="java.lang.String">ride</attribute></attributes></leg>
    <activity type="car interaction"/><leg mode="walk"><attributes><attribute name="routingMode" class="java.lang.String">car</attribute></attributes></leg>
    <activity type="work" x="10000" y="0"/></plan></person></population>'''
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        stream.write(xml)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); source = root/"source.xml.gz"; clean = root/"clean.xml.gz"
        baseline = root/"baseline.xml.gz"; candidate = root/"candidate.xml.gz"
        write(source, 5, 7); report = sanitize_population(source, clean)
        with gzip.open(clean, "rb") as stream:
            tree = ET.parse(stream)
        plans = tree.findall("./person/plan")
        assert report["layoutInvalidatedAamPlans"] == 1
        assert all("score" not in plan.attrib for plan in plans)
        assert len(plans[0].findall("activity")) == 2
        assert [leg.get("mode") for leg in plans[0].findall("leg")] == ["ride"]
        ground = tree.find("./person[@id='p2']/plan")
        assert {routing.text for routing in ground.findall("./leg/attributes/attribute[@name='routingMode']")} == {"ride"}
        write(baseline, 5, 7); write(candidate, 8, 7, extra_aam=True)
        comparison = compare_aam_score_sums(baseline, candidate)
        assert comparison["pairedAgents"] == 1 and comparison["meanPairedScoreChange"] == 3
        assert comparison["baselineAamAgents"] == 1 and comparison["candidateAamAgents"] == 1
        assert comparison["totalBestAamScoreBaseline"] == 5 and comparison["totalBestAamScoreCandidate"] == 8
        assert comparison["totalAamScoreChange"] == 3
        assert comparison["averageAamScoreChange"] == 3
        decision = evaluate_candidate(comparison, minimum_aam_users=1)
        assert decision["passedCriteria"] == 5 and decision["accepted"]
        invalid_sample = evaluate_candidate(comparison, minimum_aam_users=2)
        assert invalid_sample["passedCriteria"] == 5 and not invalid_sample["accepted"]
        exactly_three = dict(comparison, baselineAamAgents=2, candidateAamAgents=2,
                             totalAamScoreChange=1, averageAamScoreChange=1,
                             meanPairedScoreChange=-1, candidateBetterShare=0.4)
        three_vote_decision = evaluate_candidate(exactly_three, minimum_aam_users=1)
        assert three_vote_decision["passedCriteria"] == 3 and three_vote_decision["accepted"]
        exactly_two = dict(exactly_three, candidateAamAgents=1)
        two_vote_decision = evaluate_candidate(exactly_two, minimum_aam_users=1)
        assert two_vote_decision["passedCriteria"] == 2 and not two_vote_decision["accepted"]
    print("PASS: adaptive restart sanitization and three-of-five AAM decision")


if __name__ == "__main__":
    main()
