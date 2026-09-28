#!/usr/bin/env python3
"""Build against MATSim 13 (never the legacy bundled v12 JAR) and run 0,1,2.
Python stdlib only; Java 11+ required. Run from any directory.
"""
from pathlib import Path
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor
import argparse, hashlib, io, json, os, subprocess, sys, zipfile

ROOT=Path(__file__).resolve().parents[2]
MAT='https://repo.matsim.org/repository/matsim'
CENTRAL='https://repo.maven.apache.org/maven2'
INPUT='https://svn.vsp.tu-berlin.de/repos/public-svn/matsim/scenarios/countries/us/los-angeles/los-angeles-v1.0/input/'
CONTRIB=['drt','dvrp','ev','otfvis','locationchoice','sbb-extensions','common','av','taxi']
DATA=['los-angeles-v1.0-network_2019-12-10.xml.gz','los-angeles-v1.0-population-0.1pct_2019-12-09.xml.gz',
      'los-angeles-v1.0-transitSchedule_2019-12-18.xml.gz','los-angeles-v1.0-transitVehicles_2019-11-19.xml.gz',
      'los-angeles-v1.0-mode-vehicle-types_2019-12-05.xml']

def download(url,path):
    if path.exists():return
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.download')
    print('Downloading',path.name,flush=True)
    with urlopen(url,timeout=180) as r,tmp.open('wb') as w:
        while True:
            b=r.read(1024*1024)
            if not b:break
            w.write(b)
    tmp.replace(path)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--build-only',action='store_true');ap.add_argument('--smoke',type=int,default=0)
    ap.add_argument('--memory',default='12g');ap.add_argument('--java',default='java')
    ap.add_argument('--test',action='store_true',help='Compile and run regression and tiny DRT checks; no LA run')
    ap.add_argument('--output',default='run-output/aam-fare30-it2');ap.add_argument('--runtime-dir',type=Path)
    args=ap.parse_args();os.chdir(ROOT)
    cache=args.runtime_dir or ROOT/'target/aam-runtime';cache=cache.resolve();cache.mkdir(parents=True,exist_ok=True)
    release=cache/'release/matsim-13.0'
    if not (release/'matsim-13.0.jar').exists():
        archive=cache/'matsim-13.0-release.zip'
        download('https://github.com/matsim-org/matsim-libs/releases/download/13.0/matsim-13.0-release.zip',archive)
        with zipfile.ZipFile(archive) as z:z.extractall(cache/'release')
    jobs=[(f'{MAT}/org/matsim/contrib/{a}/13.0/{a}-13.0.jar',cache/f'{a}-13.0.jar') for a in CONTRIB]
    jobs +=[(f'{CENTRAL}/one/util/streamex/0.7.2/streamex-0.7.2.jar',cache/'streamex-0.7.2.jar'),
            (f'{CENTRAL}/org/apache/commons/commons-math3/3.6.1/commons-math3-3.6.1.jar',cache/'commons-math3-3.6.1.jar'),
            (f'{CENTRAL}/com/opencsv/opencsv/4.6/opencsv-4.6.jar',cache/'opencsv-4.6.jar')]
    with ThreadPoolExecutor(max_workers=6) as ex:list(ex.map(lambda pair:download(*pair),jobs))
    jars=[release/'matsim-13.0.jar']+sorted((release/'libs').glob('*.jar'))+[j[1] for j in jobs]
    cp=os.pathsep.join(map(str,jars));classes=ROOT/'target/aam-classes';classes.mkdir(parents=True,exist_ok=True)
    sources=[str(p) for folder in ['src/main/java/org/matsim/run','src/main/java/org/matsim/parkingCost'] for p in (ROOT/folder).rglob('*.java')]
    command=[args.java,'-m','jdk.compiler/com.sun.tools.javac.Main','--release','11','-cp',cp,'-d',str(classes)]+sources
    subprocess.run(command,check=True)
    if args.test:
        test_source=ROOT/'src/test/java/org/matsim/run/aam/AamRegressionChecks.java'
        subprocess.run([args.java,'-m','jdk.compiler/com.sun.tools.javac.Main','--release','11','-cp',str(classes)+os.pathsep+cp,'-d',str(classes),str(test_source)],check=True)
        subprocess.run([args.java,'--add-opens=java.base/java.lang=ALL-UNNAMED','-Djava.awt.headless=true','-Dmatsim.preferLocalDtds=true','-cp',str(classes)+os.pathsep+cp,'org.matsim.run.aam.AamRegressionChecks'],check=True)
        return
    (ROOT/'target/aam-build-provenance.json').write_text(json.dumps({'matsim':'13.0','jars':[{ 'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in jars]},indent=2))
    if args.build_only:return
    with ThreadPoolExecutor(max_workers=3) as ex:list(ex.map(lambda n:download(INPUT+n,ROOT/'run-inputs'/n),DATA))
    # Java 11 accepts this compatibility flag too; Java 17 requires it for Guice 4.
    cmd=[args.java,'--add-opens=java.base/java.lang=ALL-UNNAMED','-Xms1g','-Xmx'+args.memory,
         '-Djava.awt.headless=true','-Dmatsim.preferLocalDtds=true','-cp',str(classes)+os.pathsep+cp,
         'org.matsim.run.aam.RunDynamicAamLosAngelesScenario','scenarios/aam/la-aam-fare30-it2.config.xml',args.output]
    if args.smoke:cmd.append('--test-persons='+str(args.smoke))
    print('Running:', ' '.join(cmd[:5]),'... output:',args.output,flush=True)
    subprocess.run(cmd,check=True)

if __name__=='__main__':main()
