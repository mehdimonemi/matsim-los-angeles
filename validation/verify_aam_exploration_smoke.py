import csv, gzip, json
from pathlib import Path
import xml.etree.ElementTree as ET
from scripts.aam.score_optimizer.population import sanitize_population
root=Path('validation/aam-exploration-integration')
stage=root/'dispatch-fixed'
plans=next(stage.glob('*.output_plans.xml.gz'))
stats=list(csv.DictReader(next(stage.glob('*.drt_customer_stats_aam_drt.csv')).open(),delimiter=';'))
assert int(stats[0]['rides'])==2 and int(stats[0]['rejections'])==0, 'Iteration-zero passengers must be served'
same=sanitize_population(plans,root/'dispatch-fixed-same-layout.xml.gz','same',preserve_learning=True,previous_layout_id='same')
changed=sanitize_population(plans,root/'dispatch-fixed-changed-layout.xml.gz','changed',preserve_learning=True,previous_layout_id='same')
assert same['scoresCleared']==0 and same['layoutInvalidatedAamPlans']==0
assert changed['layoutInvalidatedAamPlans']>0
with gzip.open(root/'dispatch-fixed-same-layout.xml.gz') as f:
    people=ET.parse(f).getroot().findall('person')
assert any(p.find("./attributes/attribute[@name='aam_initial_exploration_done']") is not None for p in people)
report=dict(iterationZero=stats[0],unchangedRestart=same,changedRestart=changed)
(root/'verification.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
