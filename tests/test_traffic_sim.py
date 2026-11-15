import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from traffic_sim import cohort_stats, write_routes, fleet_rates, _site_folder, _run, queue_maxima, summarise, SimulationError


class AccountingTest(unittest.TestCase):
    def test_missing_vehicle_classes_do_not_silently_become_all_cars(self):
        from traffic_sim import demand
        from traffic_counts import parse_manual
        from test_traffic_counts import MANUAL
        for change in (lambda h:h.pop('buses'),lambda h:h['dual_wheeled'].update(nb=True)):
            sheet=parse_manual(MANUAL);change(sheet['heavy_vehicles'])
            with self.assertRaises(SimulationError): demand(sheet,'pm',{'nb':{}})

    def test_missing_queue_samples_are_not_zero_queues(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'queue.xml'
            for text in ('<queue-export/>', '<queue-export><data timestep="600"><lanes><lane id="a_0" queueing_length="nan"/></lanes></data></queue-export>'):
                path.write_text(text)
                with self.assertRaises(SimulationError): queue_maxima(path,{'nb':[('a',1)]},begin=600,end=4200)

    def test_summary_preserves_threshold_precision_and_missing_noise_seed(self):
        from street_design import rank
        from test_street_design import checked
        base=dict(seed=11,completed=900,offered=1000,unfinished=50,not_inserted=50,mean_delay_s=60.,
                  max_queue_m={'nb':80.},max_noise_db={'nb':72.},co2_sumo_g=400000.,nox_sumo_g=100.,vehicle_miles=10.,teleports=0)
        candidate={**base,'mean_delay_s':66.001,'co2_sumo_g':350000.}
        before=summarise([base],1000,{'CO2':1.,'NOx':1.});after=summarise([candidate],1000,{'CO2':1.,'NOx':1.})
        self.assertEqual(after['mean_delay_s'],66.001)
        self.assertEqual(after['paired_co2_kg_per_hour'], [{'seed':11,'value':350.}])
        self.assertFalse(rank({'baseline':before,'candidate':after},{'candidate':checked()})['verdicts']['candidate']['eligible'])
        incomplete={**base,'seed':23,'max_noise_db':{'nb':None}}
        self.assertIsNone(summarise([base,incomplete],1000,{'CO2':1.,'NOx':1.})['max_noise_db']['nb'])
    def test_queue_length_uses_full_chain_and_is_invariant_to_edge_splits(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "original.xml"
            original.write_text('<queue-export><data timestep="600"><lanes><lane id="approach_0" queueing_length="80"/>'
                                '<lane id="approach_1" queueing_length="75"/></lanes></data></queue-export>')
            split = Path(folder) / "split.xml"
            split.write_text('<queue-export><data timestep="600"><lanes><lane id="before_0" queueing_length="30"/>'
                             '<lane id="before_1" queueing_length="25"/><lane id="after_0" queueing_length="50"/>'
                             '<lane id="after_1" queueing_length="48"/></lanes></data></queue-export>')
            baseline = queue_maxima(original, {"nb": [("approach", 2)]}, begin=600, end=4200)
            modified = queue_maxima(split, {"nb": [("before", 2), ("after", 2)]}, begin=600, end=4200)
            self.assertEqual(baseline, {"nb": 80})
            self.assertEqual(modified, baseline)

    def test_queue_uses_simultaneous_lengths_not_sum_of_individual_temporal_peaks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "queue.xml"
            path.write_text('<queue-export>'
                            '<data timestep="599"><lanes><lane id="a_0" queueing_length="900"/></lanes></data>'
                            '<data timestep="600"><lanes><lane id="a_0" queueing_length="60"/><lane id="b_0" queueing_length="5"/></lanes></data>'
                            '<data timestep="601"><lanes><lane id="a_0" queueing_length="10"/><lane id="b_0" queueing_length="70"/></lanes></data>'
                            '<data timestep="4200"><lanes><lane id="b_0" queueing_length="900"/></lanes></data></queue-export>')
            self.assertEqual(queue_maxima(path, {"nb": [("a", 1), ("b", 1)]}, begin=600, end=4200), {"nb": 80})

    def test_unfinished_undeparted_and_missing_trips_remain_in_denominator(self):
        departures = {"done": 600, "unfinished": 700, "waiting": 800, "missing": 900}
        rows = [{"id": "done", "depart": "620", "arrival": "900", "departDelay": "20", "timeLoss": "30"},
                {"id": "unfinished", "depart": "710", "arrival": "-1", "departDelay": "10", "timeLoss": "100"},
                {"id": "waiting", "depart": "-1", "arrival": "-1"},
                {"id": "warmup", "depart": "0", "arrival": "100", "timeLoss": "0"}]
        result = cohort_stats(rows, departures, end=5100)
        self.assertEqual((result["offered"], result["completed"], result["unfinished"], result["not_inserted"]), (4, 1, 1, 2))
        self.assertEqual(result["mean_delay_s"], (50 + 110 + 4300 + 4200) / 4)

    def test_explicit_departures_are_identical_sorted_and_escape_source_ids(self):
        flows = [{"id": "nb-through-car", "type": "car", "rate": 3600, "from": "edge&a", "to": "out", "via": ["edge&a", "out"]}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "routes.xml"
            write_routes(flows, path)
            first = path.read_bytes()
            write_routes(flows, path)
            self.assertEqual(first, path.read_bytes())
            trips = ET.parse(path).getroot().findall("trip")
            cohort = [trip for trip in trips if 600 <= float(trip.get("depart")) < 4200]
            self.assertEqual(len(cohort), 3600)
            self.assertEqual(trips[0].get("from"), "edge&a")
            self.assertEqual([float(t.get("depart")) for t in trips], sorted(float(t.get("depart")) for t in trips))

    def test_fleet_factor_requires_official_region_year_and_recomputes_vmt_weighting(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rates.csv"
            path.write_text('Source: official export\nRegion,Calendar Year,Total VMT,CO2_RUNEX,NOx_RUNEX\nLos Angeles (SC),2026,100,300,1\nLos Angeles (SC),2026,300,500,2\n')
            self.assertEqual(fleet_rates(path), {"CO2": 450, "NOx": 1.75})
            path.write_text(path.read_text().replace("2026", "2020"))
            with self.assertRaises(SimulationError):
                fleet_rates(path)
            with self.assertRaises(SimulationError):
                fleet_rates(Path(folder) / "missing.csv")

    def test_fleet_rejects_nonfinite_negative_and_missing_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'rates.csv'
            for values in ('nan,300,1','100,-1,1','100,300,inf','100,,1','100,0,0'):
                path.write_text('Region,Calendar Year,Total VMT,CO2_RUNEX,NOx_RUNEX\nLos Angeles (SC),2026,'+values+'\n')
                with self.assertRaises(SimulationError): fleet_rates(path)

    def test_class_rounding_preserves_exact_counted_movement(self):
        flows = [{"id": "nb_left_" + kind, "type": kind, "rate": rate, "from": "a", "to": "b", "via": ["a", "b"]}
                 for kind, rate in (("car", 90.34), ("truck", 8.33), ("bus", 2.33))]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "routes.xml"
            write_routes(flows, path)
            trips = ET.parse(path).getroot().findall("trip")
            self.assertEqual(sum(600 <= float(trip.get("depart")) < 4200 for trip in trips), 101)

    def test_same_size_network_changes_invalidate_site_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "network.xml"
            path.write_text("aaaa")
            with patch("traffic_sim.NETWORK", path), patch("traffic_sim.sumo_tools.binary", return_value=path):
                before = _site_folder("node", {"sha256": "sheet"})
                path.write_text("bbbb")
                after = _site_folder("node", {"sha256": "sheet"})
            self.assertNotEqual(before, after)

    def test_cancellation_terminates_and_reaps_child_process(self):
        from agent_activity import RunCancelled

        class CancelSoon:
            calls = 0

            def check(self):
                self.calls += 1
                if self.calls >= 3:
                    raise RunCancelled("test cancellation")

        processes, factory = [], subprocess.Popen

        def spawn(*args, **kwargs):
            process = factory(*args, **kwargs)
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as folder, patch("traffic_sim.sumo_tools.environment", return_value={}), \
                patch("traffic_sim.subprocess.Popen", side_effect=spawn) as popen:
            with self.assertRaises(RunCancelled):
                _run([sys.executable, "-c", "import time; time.sleep(30)"], cwd=folder, log="child.log", activity=CancelSoon())
            self.assertEqual(popen.call_count, 1)
            self.assertIsNotNone(processes[0].poll())


if __name__ == "__main__":
    unittest.main()
