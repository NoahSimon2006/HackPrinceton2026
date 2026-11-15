"""Shared event balance remains independent of the retired manual comparison."""
import unittest
from stormwater import event_storage


class EventStorageTest(unittest.TestCase):
    def test_conservation_reserves_capacity_for_direct_rain(self):
        for rain, area, depth, runoff in ((.0254, 20, .15, 10), (.2, 20, .1, 5), (0, 10, .15, 0)):
            with self.subTest(rain=rain):
                result = event_storage(rain, area, depth, runoff)
                self.assertAlmostEqual(result["captured_m3"] + result["excess_m3"], runoff)
                self.assertLessEqual(result["captured_m3"], max(area * depth - rain * area, 0))
                self.assertEqual(result["direct_excess_m3"], max(rain * area - area * depth, 0))

    def test_missing_external_runoff_stays_unknown(self):
        result = event_storage(.0254, 20, .15, None)
        self.assertEqual(result["capacity_m3"], 3)
        self.assertAlmostEqual(result["direct_rain_m3"], .508)
        for key in ("runoff_m3", "captured_m3", "excess_m3"):
            self.assertIsNone(result[key])

    def test_missing_rain_does_not_become_zero(self):
        result = event_storage(None, 20, .15, 5)
        self.assertEqual(result["capacity_m3"], 3)
        for key in ("direct_rain_m3", "direct_excess_m3", "captured_m3", "excess_m3"):
            self.assertIsNone(result[key])
