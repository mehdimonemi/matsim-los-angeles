import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from .drt_fixed_suite import compare
from .fast_global import run
from .neighborhoods import METHODS
from scripts.aam.score_optimizer.common import atomic_write_layout,read_sites


class DrtFixedSuiteTests(unittest.TestCase):
    def test_each_method_uses_same_50_iteration_protocol_and_its_neighborhood(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'people.xml'
            source.write_text('<population><person id="p"><plan selected="yes" score="5"><act type="home" x="0" y="0"/><leg mode="ride"/><act type="work" x="20000" y="0"/></plan></person></population>')
            sites=root/'sites.csv';sites.write_text('id,name,x,y\nA,A,0,0\nB,B,20000,0\n')
            config=root/'config.xml';config.write_text('<config/>')
            manifest=dict(service='drt',population=str(source),projectRoot=str(root),candidateCsv=str(sites),initialLayout=['A','B'],
                compiledClassesDirectory=str(root),launcherCommand=['powershell','-a','-b','-c','-File','launch.ps1','-Memory','2g'],
                baseConfig=str(config),baseFare=30,farePerMile=2,serviceStart=25200,serviceEnd=68400,
                maximumWaitSeconds=900,maximumWalkMeters=1000,maximumWalkSeconds=1200,minimumPredictedImprovement=.01)
            for method in METHODS:
                with self.subTest(method=method):
                    stages=[];searches=[]
                    def simulate(args,output,plans,layout,waits,iterations,compile,innovation):
                        stages.append((iterations,compile,innovation));output.mkdir()
                        checkpoint=output/'output_plans.xml';checkpoint.write_text(source.read_text())
                        wait=output/'wait.csv';wait.touch();return checkpoint,wait,1
                    def optimize(population,candidates,layout,output,requested,**kwargs):
                        searches.append(requested);atomic_write_layout(output,read_sites(layout))
                        return dict(accepted=False,improvement=0)
                    with patch('scripts.aam_repair.fast_global.freeze_runtime',side_effect=lambda m,o:dict(m)):
                        result=run(manifest,root/method,simulate,optimize,method=method)
                    self.assertEqual(stages,[(5,False,True)]*8+[(10,False,False)])
                    self.assertEqual(searches,[method]*8)
                    self.assertEqual(result['totalMatsimIterations'],50)
                    self.assertEqual(result['searchMethod'],method)
                    self.assertEqual(json.loads((root/method/'manifest.json').read_text())['searchMethod'],method)

    def package(self,root):
        package=root/'package';package.mkdir()
        manifest=dict(service='drt',population='original.xml',populationHash='p',scoringHash='s',supplyFareHash='f',
            initialLayout=['A','B'],compiledClassesDirectory='same-fixed-runtime',baseFare=30,seeds=[817])
        (package/'drt-production-manifest.json').write_text(json.dumps(manifest))
        return package

    def result(self,method):
        return dict(status='fixed_50_iteration_protocol_completed',totalMatsimIterations=50,
            finalLayout=method+'.csv',finalPlans=method+'.xml',history=[dict(matsimSeconds=1,
                optimization=dict(accepted=False,optimizerSeconds=2),
                retainedPlanMetrics=dict(scoredAamAlternativeUsers=7),
                journeyMetrics=dict(selectedAamUsers=3,attemptedRequests=4,completedAamUsers=3,rejectedRequests=1))])

    def test_independent_starts_same_package_and_incremental_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);package=self.package(root);calls=[]
            def runner(manifest,output,method):
                calls.append((method,manifest['population'],manifest['compiledClassesDirectory'],manifest['seeds']))
                self.assertEqual(manifest['initialLayout'],['A','B'])
                output.mkdir();return self.result(method)
            with patch('scripts.aam_repair.drt_fixed_suite.validate'):
                rows=compare(package,root/'output',runner=runner)
            self.assertEqual([c[0] for c in calls],list(METHODS))
            self.assertTrue(all(c[1:] == calls[0][1:] for c in calls))
            self.assertEqual(len(rows),4)
            self.assertEqual(rows[0]['selectedAamUsers'],3)
            self.assertEqual(rows[0]['scoredAamAlternativeUsers'],7)
            self.assertEqual(json.loads((root/'output/result.json').read_text())['totalMatsimIterations'],200)
            self.assertEqual(len(json.loads((root/'output/comparison.json').read_text())),4)

    def test_failure_preserves_completed_method_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);package=self.package(root)
            def runner(manifest,output,method):
                if method==METHODS[1]:raise RuntimeError('stage failed')
                return self.result(method)
            with patch('scripts.aam_repair.drt_fixed_suite.validate'):
                with self.assertRaises(RuntimeError):compare(package,root/'output',runner=runner)
            self.assertEqual(len(json.loads((root/'output/comparison.json').read_text())),1)
            self.assertEqual(json.loads((root/'output/failure.json').read_text())['method'],METHODS[1])

    def test_invalid_methods_rejected_before_validation_or_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for methods in ([],['global','global'],['unknown']):
                with self.assertRaises(ValueError):compare(root,root/'output',methods)
            self.assertFalse((root/'output').exists())


if __name__=='__main__':unittest.main()
