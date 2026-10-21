import copy
import unittest
from .aircraft_operations import dispatch, slot


def assumptions():
    return dict(batteryKWh=80,maximumRangeMeters=80000,chargerKW=300,maximumDutySeconds=13*3600,
        maintenanceAfterFlightSeconds=10*3600,energyKWhPerMeter=.001,takeoffEnergyKWh=2,reserveKWh=15,
        turnaroundSeconds=600,padOccupancySeconds=60,maintenanceSeconds=1800,chargingEfficiency=.9,
        maximumFleet=3,reserveAircraft=1,padsPerSite={"A":1,"B":1},chargersPerSite={"A":1,"B":1},costs=None,
        calibration="SYNTHETIC REGRESSION VALUES ONLY; not aircraft specifications")


class OperationsTests(unittest.TestCase):
    def test_reuse_energy_continuity_and_charger_capacity(self):
        flights=[dict(id=str(i),origin="A" if i%2==0 else "B",destination="B" if i%2==0 else "A",
                      departure=25200+i*1800,arrival=25700+i*1800,meters=22000) for i in range(8)]
        a=assumptions();r=dispatch(flights,a)
        self.assertEqual(r["aircraftUsed"],1);self.assertEqual(len(r["served"]),8)
        self.assertTrue(r["charging"]);self.assertIsNone(r["operatingCost"])
        self.assertTrue(all(f["socAfter"]>=15-1e-9 for f in r["served"]))
        previous=None
        for f in r["served"]:
            if previous:self.assertEqual(previous["destination"],f["origin"])
            previous=f
        for site in r["chargerCalendars"].values():
            for intervals in site:
                intervals=sorted(intervals)
                self.assertTrue(all(x[1]<=y[0] for x,y in zip(intervals,intervals[1:])))
        reference=dispatch(flights,a,reuse=False)
        self.assertEqual(len(reference["served"]),2);self.assertEqual(len(reference["rejected"]),6)
        a["maximumFleet"]=2;a["chargersPerSite"]={"A":0,"B":0}
        limited=dispatch(flights,a)
        self.assertTrue(limited["rejected"])
        self.assertIn("charging_capacity_or_time",limited["rejected"][0]["bindingCandidates"])

    def test_constraints_are_binding_and_explicit(self):
        flight=dict(id="1",origin="A",destination="B",departure=1000,arrival=1500,meters=22000)
        for change,reason in ((dict(maximumRangeMeters=10000),"range"),(dict(batteryKWh=30),"battery_reserve"),
                              (dict(maximumDutySeconds=100),"duty"),(dict(padsPerSite={"A":0,"B":1}),"pad_capacity"),
                              (dict(maintenanceAfterFlightSeconds=100),"maintenance_interval")):
            a={**assumptions(),**change};self.assertEqual(dispatch([flight],a)["rejected"][0]["reason"],reason)
        collision={**flight,"id":"2"}
        self.assertEqual(dispatch([flight,collision],assumptions())["rejected"][0]["reason"],"pad_capacity")

    def test_costs_are_separate_explicit_inputs(self):
        a=assumptions();a["costs"]=dict(aircraftPerDay=100,flightHour=200,crewDutyHour=50,electricityPerKWh=.2,maintenanceEvent=100)
        r=dispatch([dict(id="1",origin="A",destination="B",departure=1000,arrival=1500,meters=22000)],a)
        self.assertAlmostEqual(r["operatingCost"],sum(r["costBreakdown"].values()))
        self.assertEqual(r["costBreakdown"]["aircraft"],200) # operating + withheld reserve
        self.assertEqual(slot([[(0,10),(20,30)]],5,5,30),(10,0))

    def test_maintenance_before_crossing_interval(self):
        a=assumptions();a["maximumFleet"]=2;a["maintenanceAfterFlightSeconds"]=750;a["maintenanceSeconds"]=600
        flights=[dict(id=str(i),origin="A" if i%2==0 else "B",destination="B" if i%2==0 else "A",
                      departure=1000+i*1800,arrival=1500+i*1800,meters=10000) for i in range(3)]
        r=dispatch(flights,a)
        self.assertEqual(len(r["served"]),3);self.assertEqual(len(r["maintenance"]),2)
        a["maintenanceSeconds"]=2000
        r=dispatch(flights,a)
        self.assertIn("turnaround_or_maintenance",r["rejected"][0]["bindingCandidates"])


if __name__=="__main__":unittest.main()
