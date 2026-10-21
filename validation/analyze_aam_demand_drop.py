"""Read-only diagnosis of the completed Global run; no model launch."""
import collections
import gzip
import json
import math
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET

root=Path('run-output/drt-global-choice-fixed-20261010-231924')
stage_rows=[]
for stage in [f'stage-{i:02d}' for i in range(1,9)]+['final-convergence']:
    decision=json.loads((root/(stage+'-decision.json')).read_text())
    metrics=decision['journeyMetrics']
    stage_rows.append(dict(stage=stage,selected=metrics['selectedAamUsers'],
        requests=metrics['attemptedRequests'],completed=metrics['completedAamUsers'],
        retainedScoredAlternatives=decision['retainedPlanMetrics']['scoredAamAlternativeUsers']))
plans=next((root/'final-convergence').glob('*.output_plans.xml.gz'))
gaps=[];affected=0;air_users=0;examples=[]
with gzip.open(plans,'rb') as stream:
    for _,person in ET.iterparse(stream,events=('end',)):
        if person.tag!='person':continue
        def score(plan):
            try:return float(plan.get('score','nan'))
            except ValueError:return math.nan
        scored=[p for p in person.findall('plan') if math.isfinite(score(p))]
        air=[p for p in scored if any(l.get('mode')=='aam_drt' for l in p.findall('leg'))]
        ground=[p for p in scored if not any(l.get('mode')=='aam_drt' for l in p.findall('leg'))]
        if air and ground:
            air_users+=1;a=max(air,key=score);g=max(ground,key=score)
            gap=score(a)-score(g);gaps.append(gap)
            ac=collections.Counter(l.get('mode') for l in a.findall('leg'))
            gc=collections.Counter(l.get('mode') for l in g.findall('leg'))
            affected+=int(gc['car']>0 and ac['car']==0)
            if len(examples)<5:examples.append(dict(person=person.get('id'),aamScore=score(a),groundScore=score(g),
                aamLegModes=dict(ac),groundLegModes=dict(gc)))
        person.clear()
report=dict(stageMetrics=stage_rows,scoredAamAndGroundUsers=air_users,
    aamBetterThanBestGround=sum(v>0 for v in gaps),medianAamMinusGroundScore=statistics.median(gaps),
    meanAamMinusGroundScore=statistics.mean(gaps),groundCarUsersWithoutCarInAamPlan=affected,examples=examples)
Path('validation/drt-global-demand-drop-diagnosis.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='examples'},indent=2))
