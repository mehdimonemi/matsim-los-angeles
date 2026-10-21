import csv, math, json
from pathlib import Path
root=Path('run-output/drt-four-optimizers-choice-fixed-20261011-122109/global')
ports=[(float(p['x']),float(p['y'])) for p in csv.DictReader((root/'layout-00.csv').open())]
rows=list(csv.DictReader((root/'stage-01/aam-choice-set/layout/candidates.csv').open()))
for radius in [5,15,30,50,100]:
    people=set();trips=0
    for r in rows:
        o=(float(r['origin_x']),float(r['origin_y']));d=(float(r['destination_x']),float(r['destination_y']))
        a={i for i,p in enumerate(ports) if math.dist(o,p)<=radius*1609.344};b={i for i,p in enumerate(ports) if math.dist(d,p)<=radius*1609.344}
        if any(i!=j for i in a for j in b):people.add(r['person']);trips+=1
    print(radius, len(people),trips,round(len(people)/18659*100,2),flush=True)
