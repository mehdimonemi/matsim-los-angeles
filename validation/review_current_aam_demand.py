"""Read-only output diagnosis; writes only this review's summary."""
import csv, gzip, json, math, statistics, collections
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path('run-output/drt-four-optimizers-choice-fixed-20261011-122109')
OUT=Path('validation/aam-demand-review-20261011')
OUT.mkdir(exist_ok=True)
def stats(v):
    v=sorted(v)
    return dict(n=len(v),median=statistics.median(v),mean=statistics.mean(v),p10=v[int(.1*(len(v)-1))],p90=v[int(.9*(len(v)-1))]) if v else {}
report={}
for method in ['global','all-vp-k10','one-vp-k10','adaptive']:
    r={'stages':[]};report[method]=r
    for name in [f'stage-{i:02d}' for i in range(1,9)]+['final-convergence']:
        f=ROOT/method/(name+'-decision.json')
        if not f.exists():continue
        d=json.loads(f.read_text());j=d['journeyMetrics'];o=d.get('optimization',{})
        r['stages'].append(dict(stage=name,users=j['completedAamUsers'],requests=j['attemptedRequests'],rejects=j['rejectedRequests'],wait=j['meanBoardedPassengerWaitSeconds'],alternatives=d['retainedPlanMetrics']['scoredAamAlternativeUsers'],screen=o.get('inputLayoutScreening'),provenance=d['provenance']))
    final=ROOT/method/'final-convergence'
    if not (ROOT/method/'final-convergence-decision.json').exists():continue
    cfg=ET.parse(next(final.glob('*.output_config.xml'))).getroot()
    r['config']={}
    for mod in cfg.findall('module'):
        if mod.get('name') in ['qsim','strategy','aam','planCalcScore']:
            r['config'][mod.get('name')]={'params':{p.get('name'):p.get('value') for p in mod.findall('param')},'sets':[{p.get('name'):p.get('value') for p in ps.findall('param')} for ps in mod.iter('parameterset') if ps.get('type')!='activityParams']}
    records=[];popmu=[]
    with gzip.open(next(final.glob('*.output_plans.xml.gz')),'rb') as f:
        for _,p in ET.iterparse(f,events=['end']):
            if p.tag!='person':continue
            attrs={a.get('name'):a.text for a in p.findall('attributes/attribute')}
            if attrs.get('subpopulation')!='person':p.clear();continue
            mu=float(attrs.get('marginalUtilityOfMoney','1'));popmu.append(mu)
            plans=[pl for pl in p.findall('plan') if math.isfinite(float(pl.get('score','nan')))];air=[];ground=[]
            for pl in plans:
                (air if any(l.get('mode')=='aam_drt' for l in pl.findall('leg')) else ground).append(pl)
            if air and ground:
                a=max(air,key=lambda x:float(x.get('score')));g=max(ground,key=lambda x:float(x.get('score')))
                legs=a.findall('leg');al=[l for l in legs if l.get('mode')=='aam_drt'];dist=sum(float(l.find('route').get('distance','0')) for l in al)/1609.344
                fare=30*len(al)+2*dist
                pa={x.get('name'):x.text for x in a.findall('attributes/attribute')}
                records.append(dict(gap=float(a.get('score'))-float(g.get('score')),mu=mu,fare=fare,airlegs=len(al),miles=dist,kind=pa.get('aam_alternative_kind'),modes=dict(collections.Counter(l.get('mode') for l in legs)),groundModes=dict(collections.Counter(l.get('mode') for l in g.findall('leg')))))
            p.clear()
    r['scoreAnalysis']=dict(compared=len(records),gap=stats([x['gap'] for x in records]),positive=sum(x['gap']>0 for x in records),within10=sum(x['gap']>=-10 for x in records),fare=stats([x['fare'] for x in records]),muAll=stats(popmu),muAam=stats([x['mu'] for x in records]),kinds=dict(collections.Counter(x['kind'] for x in records)),noFarePositive=sum(x['gap']+x['mu']*x['fare']>0 for x in records),halfFarePositive=sum(x['gap']+.5*x['mu']*x['fare']>0 for x in records),carLost=sum(x['groundModes'].get('car',0)>0 and x['modes'].get('car',0)==0 for x in records),airMilesPerPlan=stats([x['miles'] for x in records]))
    (OUT/(method+'-plan-comparisons.json')).write_text(json.dumps(records,indent=2))
    print(method,json.dumps(r['scoreAnalysis']),flush=True)
(OUT/'summary.json').write_text(json.dumps(report,indent=2))
print('Saved',OUT/'summary.json')
