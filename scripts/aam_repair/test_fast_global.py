import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from .fast_global import run
from scripts.aam.score_optimizer.common import atomic_write_layout,read_sites
from scripts.aam.score_optimizer.optimizer import ground_disutility, observed_ground_scores
from .reporting import funnel


class FastGlobalTests(unittest.TestCase):
    def test_ground_history_excludes_unscored_and_physical_air_options(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'plans.xml'
            p.write_text('<population><person id="p"><plan score="8"><leg mode="ride"/></plan>'
                         '<plan><leg mode="car"/></plan><plan score="20"><leg mode="aam_drt"/></plan>'
                         '<plan score="30"><leg mode="ride"><attributes><attribute name="routingMode">aam</attribute>'
                         '</attributes></leg></plan></person></population>')
            history=observed_ground_scores(p)
            self.assertEqual(history['p']['score'],30)
            self.assertEqual(history['p']['source'],str(p.resolve()))
            self.assertIn('ride',history['p']['planXml'])

    def test_exact_40_learning_plus_10_fixed_no_probes_or_validation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/"people.xml"
            source.write_text('<population><person id="p"><plan selected="yes" score="5"><act type="home" x="0" y="0"/><leg mode="walk"/><act type="work" x="1" y="0"/></plan></person></population>')
            sites=root/"sites.csv";sites.write_text("id,x,y\nA,0,0\nB,1,0\n")
            config=root/"config.xml";config.write_text("<config/>")
            m=dict(service="drt",population=str(source),projectRoot=str(root),candidateCsv=str(sites),initialLayout=["A","B"],
                   compiledClassesDirectory=str(root),launcherCommand=["powershell","-a","-b","-c","-File","launch.ps1","-Memory","2g"],
                   baseConfig=str(config),baseFare=30,farePerMile=2,serviceStart=25200,serviceEnd=68400,
                   maximumWaitSeconds=900,maximumWalkMeters=1000,maximumWalkSeconds=1200,minimumPredictedImprovement=.01)
            calls=[];optimizations=[]
            def simulate(args,out,plans,layout,waits,iterations,compile,innovation):
                calls.append((iterations,compile,innovation));out.mkdir()
                scored=out/"output_plans.xml";scored.write_text(source.read_text());wait=out/"wait.csv";wait.touch()
                return scored,wait,1
            def optimize(population,candidates,layout,out,method,**kwargs):
                optimizations.append(kwargs)
                atomic_write_layout(out,read_sites(layout))
                return dict(accepted=False,improvement=0)
            with patch("scripts.aam_repair.fast_global.freeze_runtime",side_effect=lambda m,o:dict(m)):
                result=run(m,root/"run",simulate,optimize)
            self.assertEqual(calls,[(5,False,True)]*8+[(10,False,False)])
            self.assertEqual(len(optimizations),8)
            self.assertEqual(result["totalMatsimIterations"],50)
            self.assertFalse(result["simulationConvergenceClaim"])
            self.assertEqual(optimizations[0]["maximum_walk_distance"],1000)
            self.assertEqual(optimizations[0]['ground_score_history']['p']['score'],5)
            self.assertEqual(optimizations[0]['max_access_distance_miles'],5)
            self.assertEqual(optimizations[0]['max_egress_distance_miles'],5)
            self.assertTrue(optimizations[0]['allow_pre_service_requests'])
            self.assertEqual(json.loads((root/"run/manifest.json").read_text())["candidateProbeSimulations"],0)
            self.assertTrue((root/"run/final-convergence-input.xml.gz.observed-plans.jsonl").is_file())
            m['maximumConvergenceIterations']=20
            with patch("scripts.aam_repair.fast_global.freeze_runtime",side_effect=lambda m,o:dict(m)),patch('scripts.aam_repair.fast_global.assess',side_effect=[dict(stable=False),dict(stable=True)]):
                extended=run(m,root/'extended',simulate,optimize)
            self.assertEqual(extended['totalMatsimIterations'],60)
            self.assertEqual(extended['convergenceIterations'],20)
            self.assertEqual(extended['status'],'observed_tail_stability')
            self.assertEqual(extended['history'][-1]['provenance']['scoresCleared'],0)

    def test_walk_limits_apply_to_analytical_feeders(self):
        distance=np.asarray([[2000.]])
        unrestricted=ground_disutility(distance,np.asarray([1.]))
        limited=ground_disutility(distance,np.asarray([1.]),1000,1200)
        self.assertGreaterEqual(limited[0,0],unrestricted[0,0])

    def test_global_drt_funnel_requires_physical_air_and_actual_requests(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);plans=root/'plans.xml';events=root/'events.xml'
            plans.write_text('<population><person id="marker"><plan selected="yes" type="aam" score="4"><leg mode="ride"/></plan></person>'
                '<person id="candidate"><plan selected="yes" score="5"><leg mode="ride"/></plan><plan><leg mode="aam_drt"/></plan></person>'
                '<person id="served"><plan selected="yes" score="8"><leg mode="aam_drt"/></plan></person>'
                '<person id="truck"><attributes><attribute name="subpopulation">freight</attribute></attributes><plan selected="yes"><leg mode="freight"/></plan></person></population>')
            events.write_text('<events><event time="26000" type="DrtRequest submitted" mode="aam_drt" person="served" request="r"/>'
                '<event time="26100" type="passenger picked up" mode="aam_drt" request="r" vehicle="aam_drt_1"/>'
                '<event time="27000" type="passenger dropped off" mode="aam_drt" request="r"/>'
                '<event time="27200" type="actstart" person="served" actType="work"/></events>')
            counts,_=funnel(events,plans,service='drt')
            self.assertEqual(counts['passengerAgentsEvaluated'],3)
            self.assertEqual(counts['genuineAamAlternativeUsers'],2)
            self.assertEqual(counts['scoredAamAlternativeUsers'],1)
            self.assertEqual(counts['selectedAamUsers'],1)
            self.assertEqual(counts['markerOnlyPlans'],1)
            self.assertEqual(counts['groundFallbackPlans'],1)
            self.assertEqual(counts['attemptedRequests'],1)
            self.assertEqual(counts['completedAamUsers'],1)
            self.assertEqual(counts['completedJourneys'],1)
            # Experienced-plan files may omit subpopulation attributes.
            plans.write_text(plans.read_text().replace('<attributes><attribute name="subpopulation">freight</attribute></attributes>',''))
            counts,_=funnel(events,plans,service='drt',passenger_ids={'marker','candidate','served'})
            self.assertEqual(counts['passengerAgentsEvaluated'],3)


if __name__=="__main__":unittest.main()
