"""Exact reduced solver for the supplied z/s/q binary formulation.

Eliminate q by selecting each traveler's best feasible alternative, then enumerate
the z layouts within the swap bound. This is an exact solution method for the
additive formulation, not a claim that a simulation-based problem is solved.
No unobserved/uncertified route is silently assigned a synthetic coefficient.
"""
from dataclasses import dataclass
from itertools import combinations
import math
import time


@dataclass(frozen=True)
class Alternative:
    person: str
    sites: frozenset[str]  # empty = ground; can cover several flights in a daily plan
    score: float
    feasible: bool = True
    plan_id: str = ""


def objective(alternatives, layout):
    scores, choices = {}, {}
    for a in alternatives:
        if a.feasible and a.sites <= layout and (a.person not in scores or a.score > scores[a.person]):
            scores[a.person], choices[a.person] = a.score, a.plan_id
    people = {a.person for a in alternatives}
    if scores.keys() != people:
        return -math.inf, {}
    return math.fsum(scores.values()), choices


def solve(alternatives, candidates, incumbent, swaps=1, minimum_improvement=0.,
          time_limit=60., legacy_current_users=None, allowed_layouts=None):
    alternatives = list(alternatives)
    protection_alternatives = alternatives
    candidates, incumbent = frozenset(candidates), frozenset(incumbent)
    if not incumbent <= candidates or swaps < 0 or minimum_improvement < 0 or time_limit <= 0:
        raise ValueError("Invalid candidate set, incumbent, swap/improvement/time bound")
    if any(not math.isfinite(a.score) or not a.sites <= candidates for a in alternatives):
        raise ValueError("Invalid score or alternative sites")
    if legacy_current_users is not None:
        # Original slides: current AAM users must choose an AAM pair; explicitly
        # different from the population + ground outside-option objective.
        alternatives = [a for a in alternatives if a.person in legacy_current_users and a.sites]
    else:
        people = {a.person for a in alternatives}
        grounded = {a.person for a in alternatives if not a.sites and a.feasible}
        if people != grounded:
            raise ValueError("Every eligible traveler needs a feasible ground outside option")
    before, _ = objective(alternatives, incumbent)
    population_before, _ = objective(protection_alternatives, incumbent)
    if not math.isfinite(before):
        raise ValueError("Incumbent infeasible under current estimates; repair coefficients first")
    # Valid relaxation: independently open every site for each person.
    upper, _ = objective(alternatives, candidates)
    best, best_layout, evaluated = before, incumbent, 1
    started, complete = time.monotonic(), True
    def layouts():
        if allowed_layouts is not None:
            for layout in allowed_layouts:
                layout=frozenset(layout)
                if not layout<=candidates or len(layout)!=len(incumbent) or len(incumbent-layout)>swaps:
                    raise ValueError("Invalid permitted neighborhood layout")
                if layout!=incumbent:yield layout
        else:
            for count in range(1,min(swaps,len(incumbent),len(candidates-incumbent))+1):
                for removed in combinations(sorted(incumbent),count):
                    for added in combinations(sorted(candidates-incumbent),count):
                        yield (incumbent-set(removed))|set(added)
    for layout in layouts():
        if time.monotonic()-started >= time_limit:
            complete = False
            break
        value, _ = objective(alternatives, layout)
        protected, _ = objective(protection_alternatives, layout)
        evaluated += 1
        # Non-decreasing aggregate score constraint uses SAME coefficients.
        if protected >= population_before-1e-9 and value >= before and value > best + 1e-10:
            best, best_layout = value, frozenset(layout)
    bound = best if complete else max(best, upper)
    propose = best-before > minimum_improvement + 1e-10
    return {"solver": "exact-enumeration-of-reduced-z-s-q-MIP",
            "status": "optimal" if complete else "time_limit",
            "incumbentObjective": best, "bestBound": bound,
            "absoluteGap": bound-best, "relativeGap": (bound-best)/max(1., abs(best)),
            "baselineObjective": before, "predictedImprovement": best-before,
            "baselinePopulationObjective":population_before,
            "predictedPopulationImprovement":objective(protection_alternatives,best_layout)[0]-population_before,
            "proposal": sorted(best_layout if propose else incumbent),
            "mathematicalBestLayout": sorted(best_layout), "proposeChange": propose,
            "layoutsEvaluated": evaluated, "swapBound": swaps,
            "objective": "legacy_current_aam_users" if legacy_current_users is not None else "eligible_population_with_ground",
            "optimalityScope": "current coefficients, candidate universe, swap bound; NOT MATSim global optimality"}


def paired_acceptance(incumbent_runs, proposal_runs, minimum_improvement=0., critical_value=2.776):
    """Paired common-seed aggregate scores; default t(4) 97.5% => >=5 replicates.

    Comparison rule is fixed before inspecting outcomes. This function does not
    claim independent simulation replications when handed correlated iterations.
    """
    if not math.isfinite(minimum_improvement) or minimum_improvement < 0 or not math.isfinite(critical_value) or critical_value <= 0:
        raise ValueError("Invalid acceptance threshold or critical value")
    if len(incumbent_runs) != len(proposal_runs) or len(incumbent_runs) < 5:
        raise ValueError("At least five paired independent-seed runs required")
    differences = []
    for old, new in zip(incumbent_runs, proposal_runs):
        if old.get("classSnapshotHash")!=new.get("classSnapshotHash"):
            raise ValueError("Incomparable compiled runtime snapshots")
        for key in ("seed", "populationHash", "scoringHash", "supplyFareHash", "eligibleIdsHash"):
            if key not in old or old[key] != new.get(key):
                raise ValueError("Incomparable runs: " + key)
        if old["scores"].keys() != new["scores"].keys():
            raise ValueError("Population mismatch, missing/stuck persons must not be dropped")
        if any(not math.isfinite(v) for r in (old,new) for v in r["scores"].values()):
            raise ValueError("Non-finite observed scores")
        differences.append(math.fsum(new["scores"].values())-math.fsum(old["scores"].values()))
    if len({r["seed"] for r in incumbent_runs}) != len(incumbent_runs):
        raise ValueError("Replicate seeds must be distinct")
    mean = math.fsum(differences)/len(differences)
    se = math.sqrt(sum((d-mean)**2 for d in differences)/(len(differences)-1)/len(differences))
    lower = mean-critical_value*se
    return {"accepted": lower > minimum_improvement, "realizedImprovement": mean,
            "pairedDifferences": differences, "standardError": se, "lowerConfidenceBound": lower,
            "criticalValue": critical_value, "minimumImprovement": minimum_improvement,
            "rule": "paired lower confidence bound strictly above minimum improvement"}
