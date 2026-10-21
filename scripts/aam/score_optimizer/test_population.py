import gzip
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from .population import best_aam_scores, population_score_metrics, sanitize_population
from .optimizer import ScoreObjective, UserData
from .screening import TripScreen
from .population import is_genuine_aam_trip as is_aam, operational_request_metrics
import numpy as np


class PopulationTests(unittest.TestCase):
    def test_learning_restart_preserves_unchanged_routes_scores_and_selection(self):
        with tempfile.TemporaryDirectory() as d:
            source,target=Path(d)/'source.xml',Path(d)/'target.xml'
            source.write_text('<population><person id="p"><plan score="9" selected="yes"><act type="home"/><leg mode="aam_drt"><route distance="100"/></leg><act type="work"/></plan><plan score="7" selected="no"><leg mode="car"/></plan></person></population>')
            report=sanitize_population(source,target,'layout',preserve_learning=True,previous_layout_id='layout')
            plans=ET.parse(target).findall('./person/plan')
            self.assertEqual([p.get('score') for p in plans],['9','7'])
            self.assertEqual(plans[0].find('leg').get('mode'),'aam_drt')
            self.assertEqual(plans[0].get('selected'),'yes')
            self.assertEqual(report['scoresCleared'],0)
            self.assertTrue(report['sameLayoutPreserved'])

    def test_changed_layout_keeps_air_intent_and_ground_learning(self):
        with tempfile.TemporaryDirectory() as d:
            source,target=Path(d)/'source.xml',Path(d)/'target.xml'
            source.write_text('<population><person id="p"><plan score="9" selected="yes"><attributes><attribute name="aam_park_mode">car</attribute><attribute name="aam_park_vertiport">old</attribute></attributes><act type="home"/><leg mode="aam_drt"/><act type="work"/></plan><plan score="7" selected="no"><leg mode="car"/></plan></person></population>')
            report=sanitize_population(source,target,'new',preserve_learning=True,previous_layout_id='old')
            air,ground=ET.parse(target).findall('./person/plan')
            self.assertIsNone(air.get('score'));self.assertEqual(ground.get('score'),'7')
            self.assertEqual(air.find('leg').get('mode'),'aam')
            self.assertEqual(air.find("./attributes/attribute[@name='aam_park_mode']").text,'car')
            self.assertIsNone(air.find("./attributes/attribute[@name='aam_park_vertiport']"))
            self.assertEqual(report['scoresCleared'],1)

    def test_analysis_adoption_uses_events_and_physical_modes(self):
        self.assertFalse(is_aam(dict(modes='ride',main_mode='aam',longest_distance_mode='aam')))
        self.assertFalse(is_aam(dict(modes='aam')))
        self.assertTrue(is_aam(dict(modes='ride-aam_drt-walk')))
        rows=[dict(person='p',pickup_s='30000',dropoff_s='30500'),dict(person='p',pickup_s='40000',dropoff_s='40500'),
              dict(person='rejected',rejected='true'),dict(person='unfinished',pickup_s='50000')]
        self.assertEqual(operational_request_metrics(rows),dict(actualAamRequests=4,actualAamBoardings=3,
            completedAamRequests=2,completedAamUsers=1,rejectedAamRequests=1))

    def test_physical_checkpoint_is_ground_until_routed_again(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target=Path(directory)/'source.xml',Path(directory)/'target.xml'
            source.write_text('''<population><person id="p"><plan selected="yes" type="aam" score="9"><attributes><attribute name="aam_park_mode">car</attribute></attributes>
                <act type="home" x="0" y="0" end_time="08:00:00"/><leg mode="ride"/><act type="aam interaction"/><leg mode="aam_drt"/><act type="aam interaction"/><leg mode="walk"/><act type="work" x="20000" y="0"/></plan></person></population>''')
            sanitize_population(source,target)
            root=ET.parse(target);plan=root.find('./person/plan')
            self.assertEqual(plan.get('type'),'ground')
            self.assertEqual([leg.get('mode') for leg in plan.findall('leg')],['ride'])
            self.assertIsNone(plan.find("./attributes/attribute[@name='aam_park_mode']"))
            record=root.find('./person/attributes/attribute').text
            self.assertIn('trip=0',record);self.assertIn('departure=08:00:00',record);self.assertIn('layout_invalidated',record)
            self.assertEqual(population_score_metrics(target)['selectedAamUsers'],0)

    def test_physical_air_is_required_even_for_unscored_selected_plans(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plans.xml'
            path.write_text('''<population>
              <person id="fallback"><plan selected="yes" type="aam" score="999">
                <act type="home" x="0" y="0"/><leg mode="ride"><attributes><attribute name="routingMode">aam</attribute></attributes></leg><act type="work" x="20000" y="0"/>
              </plan></person>
              <person id="intent"><plan selected="yes" type="aam" score="500"><leg mode="aam"/></plan></person>
              <person id="ground"><plan selected="yes" score="10"><leg mode="ride"/></plan><plan selected="no" score="5"><leg mode="aam_drt"/></plan></person>
              <person id="air"><plan selected="yes"><leg mode="aam_drt"/></plan></person>
              </population>''')
            self.assertEqual(best_aam_scores(path), {'ground': 5.0})
            metrics = population_score_metrics(path)
            self.assertEqual(metrics['selectedAamUsers'], 1)
            self.assertEqual(metrics['scoredAamAlternativeUsers'], 1)
            self.assertEqual(metrics['markerOnlyPlans'], 2)
            self.assertEqual(metrics['groundFallbackPlans'], 1)

    def test_restart_keeps_ground_fallback_ground_and_preserves_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/'source.xml', Path(directory)/'target.xml.gz'
            source.write_text('''<population><person id="p"><plan selected="yes" type="aam" score="5"><attributes><attribute name="aam_park_mode">car</attribute></attributes>
                <act type="home" x="0" y="0" end_time="08:00:00"/><leg mode="walk"><attributes><attribute name="routingMode">aam</attribute></attributes></leg><act type="aam interaction"/><leg mode="ride"/><act type="work" x="20000" y="0"/>
                </plan></person></population>''')
            report = sanitize_population(source, target)
            self.assertEqual(report['layoutInvalidatedAamPlans'], 0)
            with gzip.open(target) as stream:
                root = ET.parse(stream)
            plan = root.find('./person/plan')
            self.assertEqual(plan.get('type'), 'ground')
            self.assertEqual([leg.get('mode') for leg in plan.findall('leg')], ['ride'])
            self.assertIsNone(plan.find("./attributes/attribute[@name='aam_park_mode']"))
            self.assertIn('ground_fallback', root.find('./person/attributes/attribute').text)
            self.assertEqual(population_score_metrics(target)['selectedAamUsers'], 0)

    def test_vectorized_radius_and_window_screen_match_direct_distance(self):
        users = UserData(ids=['p'], origins=np.array([[0., 0.]]), destinations=np.array([[20000., 0.]]),
            scores=np.array([10.]), money_utility=np.ones(1), trip_person_index=np.array([0]),
            current_origin_site=np.array([-1]), current_destination_site=np.array([-1]),
            ground_scores=np.array([10.]), departure_seconds=np.array([30000.]), ground_trip_costs=np.array([10.]))
        sites = [dict(id='A', x=0., y=0.), dict(id='B', x=20000., y=0.), dict(id='F', x=40000., y=0.)]
        objective = ScoreObjective(users, sites, [0, 1], 0, 2, 120)
        self.assertEqual(objective.destination_distance[0, 2], 20000.)
        self.assertTrue(np.isfinite(objective.minimum_cost([0, 1])[0][0]))
        self.assertFalse(np.isfinite(objective.minimum_cost([0, 2])[0][0]))
        self.assertTrue(np.isfinite(objective.minimum_cost([0, 1])[0][0]))
        users.departure_seconds[:] = 68390
        self.assertFalse(np.isfinite(objective.minimum_cost([0, 1])[0][0]))

    def test_every_passenger_every_trip_and_layout_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'population.xml'
            path.write_text('''<population><person id="p"><plan selected="yes">
                <act type="home" x="0" y="0" end_time="08:00:00"/><leg mode="ride"/>
                <act type="work" x="20000" y="0" end_time="10:00:00"/><leg mode="ride"/>
                <act type="shopping" x="0" y="0" end_time="12:00:00"/><leg mode="walk"/>
                <act type="recreation" x="20000" y="0" end_time="14:00:00"/><leg mode="ride"/><act type="home" x="0" y="0"/>
                </plan></person><person id="stationary"><plan selected="yes"><act type="home" x="0" y="0"/></plan></person>
                <person id="freight"><attributes><attribute name="subpopulation">freight</attribute></attributes><plan selected="yes"><act type="home" x="0" y="0"/></plan></person></population>''')
            screen=TripScreen(path,[dict(x=0,y=0),dict(x=20000,y=0),dict(x=60000,y=0)])
            metrics=screen.evaluate([0,1])
            self.assertEqual(metrics['passengerAgentsEvaluated'],2)
            self.assertEqual(metrics['totalTripsEvaluated'],4)
            self.assertEqual(metrics['temporallyEligibleTrips'],4)
            self.assertEqual(metrics['screenedCandidatesForRouting'],2)
            self.assertIs(metrics,screen.evaluate([1,0]))
            self.assertEqual(screen.scans,1)
            self.assertEqual(screen.evaluate([0,2])['temporallyEligibleTrips'],0)
            self.assertEqual(screen.evaluate([0,1])['temporallyEligibleTrips'],4)
            self.assertEqual(screen.origin_distance[1,0],20000.)
            self.assertEqual(screen.destination_distance[1,0],0.)


if __name__ == '__main__':
    unittest.main()
