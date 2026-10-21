import tempfile
import unittest
from pathlib import Path
from .production_manifests import cohort, sites, create, fingerprint


class ManifestTests(unittest.TestCase):
    def test_fixed_passenger_cohort_includes_ground_only_people(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"population.xml"
            p.write_text('<population><person id="b"><attributes><attribute name="subpopulation">person</attribute></attributes><plan/></person><person id="a"><attributes><attribute name="subpopulation">person</attribute></attributes><plan/></person><person id="truck"><attributes><attribute name="subpopulation">freight</attribute></attributes><plan/></person></population>')
            ids,counts=cohort(p)
            self.assertEqual(ids,["a","b"]);self.assertEqual(counts["totalSimulatedPersons"],3)
            before=fingerprint(p);p.write_text('<population/>');self.assertNotEqual(before,fingerprint(p))
            with self.assertRaises(ValueError):cohort(p)

    def test_duplicate_sites_and_population_ids_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"sites.csv";p.write_text("id,name,x,y\nA,one,1,2\nA,two,3,4\n")
            with self.assertRaises(ValueError):sites(p,2)
            q=Path(d)/"p.xml";q.write_text('<population><person id="a"/><person id="a"/></population>')
            with self.assertRaises(ValueError):cohort(q)

    def test_invalid_budgets_and_existing_directory_do_not_launch(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):create(Path(d),Path(d)/"out",probes=902)
            with self.assertRaises(FileExistsError):create(Path(d),Path(d))
            with self.assertRaises(ValueError):create(Path(d),Path(d)/"out",services=[])
            with self.assertRaises(ValueError):create(Path(d),Path(d)/"out",services=["drt","drt"])


if __name__=="__main__":unittest.main()
