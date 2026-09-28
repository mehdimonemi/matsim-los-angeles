"""Analyze a complete AAM run: trips, plans, baseline comparison, and fleet events."""
import argparse
import csv
import gzip
import io
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree.ElementTree import iterparse
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def open_text(path):
    return gzip.open(path,'rt',encoding='utf-8') if str(path).endswith('.gz') else open(path,encoding='utf-8')


def seconds(value):
    if value is None or value in ('','null','undefined'): return math.nan
    if ':' in value:
        h,m,s=value.split(':');return float(h)*3600+float(m)*60+float(s)
    return float(value)


def trips(path):
    with open_text(path) as stream:
        reader=csv.DictReader(stream,delimiter=';')
        if not {'person','trip_number','trav_time','modes'}.issubset(reader.fieldnames or []):
            raise ValueError(f'{path}: expected semicolon-delimited MATSim trip columns')
        return list(reader)


def is_aam(row):
    return bool({'aam','aam_drt'} & set(row.get('modes','').split('-'))) or row.get('longest_distance_mode') in ('aam','aam_drt')


def key(row): return row['person'],row['trip_number']


def save_csv(path,rows,fields):
    with path.open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)


def chart(path,title,labels,vals,ylabel='Trips',horizontal=False):
    fig,ax=plt.subplots(figsize=(max(7,len(labels)*.85),4.5),layout='constrained')
    if horizontal:ax.barh(labels,vals,color='#14828b');ax.set_xlabel(ylabel)
    else:ax.bar(labels,vals,color='#14828b');ax.set_ylabel(ylabel);ax.tick_params(axis='x',rotation=30)
    ax.set_title(title);ax.grid(axis='x' if horizontal else 'y',alpha=.2)
    fig.savefig(path,dpi=150);plt.close(fig)


TIME_BIN_EDGES=[0,5,10,15,30,45,60,120,float('inf')]
TIME_BIN_LABELS=['0–5','5–10','10–15','15–30','30–45','45–60','60–120','120+']


def time_bin(value):
    for index,(low,high) in enumerate(zip(TIME_BIN_EDGES,TIME_BIN_EDGES[1:])):
        if low <= value < high:return TIME_BIN_LABELS[index]
    return None


def access_egress_outputs(out,rows):
    """Write selected-plan access/egress counts and planned-time bin tables/charts."""
    sides=(('access','access_mode','access_minutes_planned'),('egress','egress_mode','egress_minutes_planned'))
    mode_rows=[]
    for side,mode_field,_ in sides:
        counts=Counter(r[mode_field] for r in rows)
        mode_rows.extend({'side':side,'mode':mode,'planned_trips':count,
                          'share_pct':round(100*count/len(rows),3)} for mode,count in counts.most_common())
    save_csv(out/'access_egress_mode_counts.csv',mode_rows,['side','mode','planned_trips','share_pct'])
    modes=sorted({r['mode'] for r in mode_rows})
    fig,ax=plt.subplots(figsize=(8,4.8),layout='constrained');x=np.arange(len(modes));width=.38
    for offset,(side,_,_) in zip((-.19,.19),sides):
        lookup={r['mode']:r['planned_trips'] for r in mode_rows if r['side']==side}
        ax.bar(x+offset,[lookup.get(mode,0) for mode in modes],width,label=side.title())
    ax.set_xticks(x,modes);ax.set_ylabel('Selected-plan trips');ax.set_title('AAM ground access and egress modes');ax.legend();ax.grid(axis='y',alpha=.2)
    fig.savefig(out/'access_egress_mode_counts.png',dpi=150);plt.close(fig)

    bin_rows=[];summary_rows=[]
    for side,mode_field,time_field in sides:
        side_values=[float(r[time_field]) for r in rows if math.isfinite(float(r[time_field]))]
        mode_values=sorted({r[mode_field] for r in rows})
        for mode in ['all']+mode_values:
            values=side_values if mode=='all' else [float(r[time_field]) for r in rows if r[mode_field]==mode and math.isfinite(float(r[time_field]))]
            counts=Counter(time_bin(v) for v in values)
            if values:
                summary_rows.append({'side':side,'mode':mode,'planned_trips':len(values),
                    'mean_minutes':round(float(np.mean(values)),3),'median_minutes':round(float(np.median(values)),3),
                    'p95_minutes':round(float(np.percentile(values,95)),3),'min_minutes':round(min(values),3),
                    'max_minutes':round(max(values),3)})
            for label in TIME_BIN_LABELS:
                count=counts[label]
                bin_rows.append({'side':side,'mode':mode,'time_bin_min':label,'planned_trips':count,
                                 'share_within_side_mode_pct':round(100*count/len(values),3) if values else 0})
    save_csv(out/'access_egress_time_bins.csv',bin_rows,
             ['side','mode','time_bin_min','planned_trips','share_within_side_mode_pct'])
    save_csv(out/'access_egress_time_summary.csv',summary_rows,
             ['side','mode','planned_trips','mean_minutes','median_minutes','p95_minutes','min_minutes','max_minutes'])

    fig,ax=plt.subplots(figsize=(9,5),layout='constrained');x=np.arange(len(TIME_BIN_LABELS));width=.38
    for offset,side in ((-.19,'access'),(.19,'egress')):
        lookup={r['time_bin_min']:r['planned_trips'] for r in bin_rows if r['side']==side and r['mode']=='all'}
        ax.bar(x+offset,[lookup[label] for label in TIME_BIN_LABELS],width,label=side.title())
    ax.set_xticks(x,TIME_BIN_LABELS);ax.set_xlabel('Planned ground travel time (minutes)');ax.set_ylabel('Selected-plan trips')
    ax.set_title('AAM access and egress planned travel-time distributions');ax.legend();ax.grid(axis='y',alpha=.2)
    fig.savefig(out/'access_egress_time_distribution.png',dpi=150);plt.close(fig)

    fig,axs=plt.subplots(2,1,figsize=(10,8),sharex=True,layout='constrained')
    for ax,(side,mode_field,_) in zip(axs,sides):
        mode_values=sorted({r[mode_field] for r in rows})
        bottom=np.zeros(len(TIME_BIN_LABELS))
        for mode in mode_values:
            lookup={r['time_bin_min']:r['planned_trips'] for r in bin_rows if r['side']==side and r['mode']==mode}
            values=np.array([lookup[label] for label in TIME_BIN_LABELS])
            ax.bar(TIME_BIN_LABELS,values,bottom=bottom,label=mode);bottom+=values
        ax.set_ylabel('Selected-plan trips');ax.set_title(side.title());ax.grid(axis='y',alpha=.2);ax.legend(title='Mode',ncol=3)
    axs[-1].set_xlabel('Planned ground travel time (minutes)')
    fig.suptitle('AAM ground travel-time distributions by mode')
    fig.savefig(out/'access_egress_time_distribution_by_mode.png',dpi=150);plt.close(fig)


def plan_legs(path,wanted):
    """Split selected plans at main activities, retaining stage-connected trip legs."""
    result=[]
    with open_text(path) as stream:
        for _,person in iterparse(stream,events=('end',)):
            if person.tag!='person':continue
            pid=person.get('id')
            if wanted is not None and pid not in wanted:person.clear();continue
            for plan in person.findall('plan'):
                if plan.get('selected','yes').lower() not in ('yes','true','1'):continue
                groups=[];current=[]
                for elem in plan:
                    if elem.tag in ('act','activity') and not elem.get('type','').lower().endswith(' interaction'):
                        if current:groups.append(current);current=[]
                    elif elem.tag=='leg':
                        route=elem.find('route')
                        current.append({'mode':elem.get('mode',''),'time_s':seconds(elem.get('trav_time') or (route.get('trav_time') if route is not None else ''))})
                if current:groups.append(current)
                for index,group in enumerate(groups,1):
                    air=[i for i,l in enumerate(group) if l['mode']=='aam_drt']
                    if not air:continue
                    before=[l for l in group[:air[0]] if l['mode']!='walk' or l['time_s']!=0]
                    after=[l for l in group[air[-1]+1:] if l['mode']!='walk' or l['time_s']!=0]
                    def modes(xs):return '+'.join(l['mode'] for l in xs) or '(none)'
                    def primary(xs):
                        nonwalk=[l['mode'] for l in xs if l['mode']!='walk']
                        return nonwalk[0] if nonwalk else ('walk' if xs else '(none)')
                    def duration(xs):return round(sum(l['time_s'] for l in xs if math.isfinite(l['time_s']))/60,3)
                    result.append(dict(person=pid,trip_number=str(index),access_modes=modes(before),egress_modes=modes(after),
                        access_mode=primary(before),egress_mode=primary(after),access_leg_count=len(before),egress_leg_count=len(after),
                        access_minutes_planned=duration(before),egress_minutes_planned=duration(after),flight_minutes_planned=duration(group[air[0]:air[-1]+1])))
            person.clear()
    return result


def passenger_sequence(row):
    """Hide walk connectors when a substantive ground mode exists; retain walk-only access."""
    legs=row['modes'].split('-');air=[i for i,m in enumerate(legs) if m in ('aam','aam_drt')]
    if not air:return row['modes']
    def ground(side):return ' + '.join(m for m in side if m!='walk') or 'walk'
    return ground(legs[:air[0]])+' → AAM → '+ground(legs[air[-1]+1:])


def metric_tables(source):
    """Return fleet series and final request/vehicle/trajectory tables from a directory or ZIP."""
    names=('fleet_metrics','requests','vehicles','air_trajectories')
    tables={}
    if source.is_dir():
        iterations=sorted(int(p.name.split('_')[-1]) for p in source.glob('iteration_*') if p.is_dir())
        for iteration in iterations:
            for name in names:
                path=source/f'iteration_{iteration}'/f'{name}.csv'
                if path.exists():
                    with path.open(encoding='utf-8') as stream:tables[iteration,name]=list(csv.DictReader(stream))
    else:
        with zipfile.ZipFile(source) as archive:
            iterations=sorted({int(n.split('iteration_')[1].split('/')[0]) for n in archive.namelist() if n.endswith('/fleet_metrics.csv')})
            for iteration in iterations:
                for name in names:
                    matches=[n for n in archive.namelist() if n.endswith(f'iteration_{iteration}/{name}.csv')]
                    if matches:
                        with io.TextIOWrapper(archive.open(matches[0])) as stream:tables[iteration,name]=list(csv.DictReader(stream))
    if not iterations:raise ValueError(f'No AAM metric iterations found in {source}')
    return iterations,tables


def fleet_outputs(out,source):
    iterations,tables=metric_tables(source);final=iterations[-1]
    series=[tables[i,'fleet_metrics'][0] for i in iterations]
    requests=[r for r in tables.get((final,'requests'),[]) if r.get('dropoff_s')]
    vehicles=tables.get((final,'vehicles'),[]);trajectories=tables.get((final,'air_trajectories'),[])
    save_csv(out/'fleet_by_iteration.csv',series,list(series[0]))
    chart(out/'served_passenger_requests_by_iteration.png','Served passenger flight requests by iteration',
          [str(i) for i in iterations],[int(s['served']) for s in series],ylabel='Served passenger requests')

    waits=np.array([float(r['wait_s'])/60 for r in requests]);onboard=np.array([float(r['in_vehicle_s'])/60 for r in requests])
    pickups=np.array([int(v['passenger_pickups']) for v in vehicles])
    fig,axs=plt.subplots(2,2,figsize=(12,8),layout='constrained')
    axs[0,0].bar(iterations,[int(s['served']) for s in series],color='#14828b');axs[0,0].set(title='Served passenger requests',xlabel='Iteration',ylabel='Requests',xticks=iterations)
    axs[0,1].hist(waits,bins=np.arange(0,max(16,math.ceil(max(waits,default=0))+2),1),color='#2476aa');axs[0,1].set(title='Flight pickup wait',xlabel='Minutes',ylabel='Passenger requests')
    axs[1,0].hist(onboard,bins=18,color='#e99535');axs[1,0].set(title='Passenger onboard time',xlabel='Minutes',ylabel='Passenger requests')
    axs[1,1].hist(pickups,bins=np.arange(0,max(pickups,default=0)+2)-.5,color='#575eaf');axs[1,1].set(title='Passenger pickups per aircraft',xlabel='Pickups',ylabel='Aircraft')
    for ax in axs.flat:ax.grid(axis='y',alpha=.2)
    fig.suptitle(f'AAM operations | iteration {final}');fig.savefig(out/'aam_operations.png',dpi=150);plt.close(fig)

    occupied=[t for t in trajectories if int(t['passengers'])>0];empty=[t for t in trajectories if int(t['passengers'])==0]
    fig,ax=plt.subplots(figsize=(8,4),layout='constrained');labels=['Served passenger requests','Occupied air-link traversals','Empty air-link traversals'];values=[len(requests),len(occupied),len(empty)]
    ax.barh(labels,values,color='#14828b');ax.set(title=f'Passengers and aircraft movements | iteration {final}',xlabel='Count (different units)')
    for i,value in enumerate(values):ax.text(value,i,f' {value}',va='center')
    ax.set_xlim(0,max(values or [1])*1.15);fig.savefig(out/'passengers_vs_aircraft.png',dpi=150);plt.close(fig)

    corridors=Counter(tuple(t['link'].split('_')[-2:]) for t in occupied)
    save_csv(out/'occupied_flight_corridors.csv',[{'from_vertiport':a,'to_vertiport':b,'aircraft_traversals':n} for (a,b),n in corridors.most_common()],
             ['from_vertiport','to_vertiport','aircraft_traversals'])
    if trajectories:
        ports={}
        for t in trajectories:
            a,b=t['link'].split('_')[-2:];ports[a]=(float(t['from_x']),float(t['from_y']));ports[b]=(float(t['to_x']),float(t['to_y']))
        fig,ax=plt.subplots(figsize=(10,6),layout='constrained')
        for (a,b),count in sorted(corridors.items(),key=lambda x:x[1]):
            ax.plot(*zip(ports[a],ports[b]),color='#00a6a6',lw=.7+count/7,alpha=.4)
        xs,ys=zip(*ports.values());ax.scatter(xs,ys,s=65,c='#163a5f',edgecolors='white',zorder=3)
        for name,(x,y) in ports.items():ax.annotate(name,(x,y),xytext=(4,4),textcoords='offset points',fontsize=8)
        ax.set_aspect('equal');ax.set_title(f'Occupied aircraft corridors | iteration {final}');ax.tick_params(labelbottom=False,labelleft=False,bottom=False,left=False)
        fig.savefig(out/'vertiports_and_flights.png',dpi=150);plt.close(fig)

    incomes={r['person']:float(r['hh_income_usd']) for r in requests if r.get('hh_income_usd')}
    if incomes:
        fig,ax=plt.subplots(figsize=(8,4),layout='constrained');ax.hist([v/1000 for v in incomes.values()],bins=[0,25,50,75,100,150,200,300,500,1000],color='#765ca8',edgecolor='white')
        ax.set(title=f'Income of distinct served AAM users | iteration {final}',xlabel='Household income (thousand USD)',ylabel='Distinct users')
        fig.savefig(out/'aam_user_income.png',dpi=150);plt.close(fig)
    return int(series[-1]['served'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('aam_trips',type=Path);parser.add_argument('output',type=Path)
    for name in ('baseline','plans','metrics'):parser.add_argument('--'+name,type=Path)
    args=parser.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=True)
    current=trips(args.aam_trips);aam=[r for r in current if is_aam(r)]
    summary=dict(aam_trip_records=len(aam),distinct_aam_trip_users=len({r['person'] for r in aam}),
                 all_completed_trip_records=len(current),aam_completed_trip_share_pct=round(100*len(aam)/len(current),3) if current else 0)
    modes=Counter(r.get('longest_distance_mode') or 'unknown' for r in current)
    save_csv(out/'mode_counts.csv',[dict(mode=m,trips=n,share_pct=round(100*n/len(current),3)) for m,n in modes.most_common()],['mode','trips','share_pct'])
    if modes:chart(out/'aam_mode_share.png','Completed trips by longest-distance mode',*zip(*modes.most_common(10)),horizontal=True)
    main_modes=Counter(r.get('main_mode') or 'unknown' for r in current)
    save_csv(out/'main_mode_counts.csv',[dict(main_mode=m,completed_trips=n) for m,n in main_modes.most_common()],['main_mode','completed_trips'])
    if main_modes:chart(out/'completed_main_modes.png','Completed trips by analysis main mode',*zip(*main_modes.most_common()),horizontal=True)
    distribution=Counter(r['modes'] for r in aam)
    save_csv(out/'aam_leg_mode_sequences.csv',[dict(leg_modes=m,trips=n) for m,n in distribution.most_common()],['leg_modes','trips'])
    if distribution:chart(out/'aam_leg_mode_sequences_raw.png','Raw MATSim legs, including walk connectors',*zip(*distribution.most_common(12)),horizontal=True)
    passenger=Counter(passenger_sequence(r) for r in aam)
    save_csv(out/'aam_passenger_mode_sequences.csv',[dict(sequence=m,completed_trips=n) for m,n in passenger.most_common()],['sequence','completed_trips'])
    if passenger:chart(out/'aam_leg_mode_sequences.png','Completed AAM trips: access → flight → egress',*zip(*passenger.most_common(12)),ylabel='Completed passenger trips',horizontal=True)
    if args.baseline:
        original={key(r):r for r in trips(args.baseline)};paired=[];sources=Counter();changes=[]
        for r in aam:
            old=original.get(key(r))
            if old is None or any(r.get(f)!=old.get(f) for f in ('start_activity_type','end_activity_type','start_x','start_y','end_x','end_y')):continue
            a,b=seconds(r['trav_time']),seconds(old['trav_time'])
            if not(math.isfinite(a) and math.isfinite(b)):continue
            source=old.get('longest_distance_mode') or old.get('modes') or 'unknown'
            sources[source]+=1;changes.append((a-b)/60)
            paired.append(dict(person=r['person'],trip_number=r['trip_number'],baseline_mode=source,baseline_minutes=round(b/60,3),aam_minutes=round(a/60,3),change_minutes=round((a-b)/60,3)))
        save_csv(out/'matched_aam_trips.csv',paired,['person','trip_number','baseline_mode','baseline_minutes','aam_minutes','change_minutes'])
        save_csv(out/'aam_source_modes.csv',[dict(baseline_mode=m,matched_trips=n) for m,n in sources.most_common()],['baseline_mode','matched_trips'])
        if sources:chart(out/'aam_source_modes.png','Baseline longest-distance mode of matched AAM trips',*zip(*sources.most_common()),horizontal=True)
        if changes:
            fig,ax=plt.subplots(figsize=(8,5),layout='constrained');ax.hist(changes,bins=35,color='#14828b');ax.axvline(0,color='#b13d3d',linestyle='--')
            ax.set(title='Observed AAM minus baseline trip time (uncontrolled comparison)',xlabel='Minutes (negative = AAM faster)',ylabel='Matched completed trips')
            fig.savefig(out/'aam_travel_time_change.png',dpi=150);plt.close(fig)
            summary.update(matched_baseline_trips=len(changes),mean_change_min=round(float(np.mean(changes)),3),median_change_min=round(float(np.median(changes)),3),aam_faster_pct=round(100*sum(x<0 for x in changes)/len(changes),3))
        base=Counter(r.get('longest_distance_mode') or 'unknown' for r in original.values());names=sorted(set(modes)|set(base))
        fig,ax=plt.subplots(figsize=(10,5),layout='constrained');x=np.arange(len(names))
        ax.bar(x-.2,[base[m] for m in names],.4,label='Baseline');ax.bar(x+.2,[modes[m] for m in names],.4,label='AAM scenario')
        ax.set_xticks(x,names,rotation=35,ha='right');ax.set_ylabel('Completed sample trips');ax.set_title('Completed trips by longest-distance mode: two scenarios');ax.legend()
        fig.savefig(out/'baseline_vs_aam_modes.png',dpi=150);plt.close(fig)
    if args.plans:
        access=plan_legs(args.plans,None)
        fields=['person','trip_number','access_mode','egress_mode','access_leg_count','egress_leg_count','access_modes','egress_modes','access_minutes_planned','egress_minutes_planned','flight_minutes_planned']
        save_csv(out/'aam_access_egress_planned.csv',access,fields)
        combinations=Counter((r['access_mode'],r['egress_mode']) for r in access)
        save_csv(out/'access_egress_mode_combinations.csv',[dict(access_mode=a,egress_mode=b,planned_trips=n) for (a,b),n in combinations.most_common()],['access_mode','egress_mode','planned_trips'])
        if combinations:chart(out/'access_egress_mode_combinations.png','Selected plans: access / egress',*zip(*[(a+' → '+b,n) for (a,b),n in combinations.most_common(12)]),horizontal=True)
        access_egress_outputs(out,access)
        summary['aam_selected_plan_trips_with_access_egress']=len(access)
        summary['planned_aam_trips_with_repeated_nonwalk_ground_legs']=sum(any(sum(m not in ('walk','(none)') for m in r[f].split('+'))>1 for f in ('access_modes','egress_modes')) for r in access)
    if args.metrics:
        summary['final_iteration_served_passenger_requests']=fleet_outputs(out,args.metrics)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    (out/'INTERPRETATION.txt').write_text('Sample counts only. Completed trips, selected-plan trips, and served passenger requests are separate units. Baseline pairs require person/trip number and identical activity types and coordinates; differences are not controlled causal effects. Planned times come from selected plans. Compact planned sequences omit zero-time walk connectors. Passenger-sequence charts hide walks around substantive ground modes, retaining walk-only sides; raw sequences remain in aam_leg_mode_sequences.csv and aam_leg_mode_sequences_raw.png. Hiding connectors does not remove their time from trips.\n',encoding='utf-8')
    print(json.dumps(summary,indent=2));print('Saved outputs in',out)

if __name__=='__main__':main()
