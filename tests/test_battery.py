import unittest

from controller.battery import soc_to_cell_voltage, soc_to_pack_voltage
from controller.setpoints import Setpoints


class BatteryTests(unittest.TestCase):
    def test_endpoints_and_interpolation(self):
        self.assertEqual(soc_to_cell_voltage(0), 2.5)
        self.assertEqual(soc_to_cell_voltage(100), 4.2)
        self.assertAlmostEqual(soc_to_cell_voltage(85), 4.005)
        self.assertAlmostEqual(soc_to_pack_voltage(80, 108), 426.60)

    def test_user_supplied_chart(self):
        # Expected values are transcribed independently from the supplied image.
        expected = {0: 2.50, 10: 3.15, 20: 3.35, 30: 3.46, 35: 3.52,
                    40: 3.56, 50: 3.65, 60: 3.76, 70: 3.85,
                    80: 3.95, 90: 4.06, 100: 4.20}
        for soc, voltage in expected.items():
            with self.subTest(soc=soc):
                self.assertAlmostEqual(soc_to_cell_voltage(soc), voltage)
                self.assertAlmostEqual(soc_to_pack_voltage(soc, 108), voltage * 108)
        self.assertAlmostEqual(soc_to_cell_voltage(5), 2.825)
        self.assertAlmostEqual(soc_to_cell_voltage(32.5), 3.49)
        self.assertAlmostEqual(soc_to_cell_voltage(37.5), 3.54)

    def test_invalid_inputs(self):
        for soc in (-1, 101, float('nan'), float('inf'), None, True, '80'):
            with self.subTest(soc=soc), self.assertRaises(ValueError):
                soc_to_cell_voltage(soc)
        for count in (0, -1, 108.5, True, None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                soc_to_pack_voltage(80, count)

    def test_monotonic_and_bounded(self):
        values = [soc_to_cell_voltage(i / 10) for i in range(1001)]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(2.5 <= v <= 4.2 for v in values))

    def test_adjust_reset_and_no_hvc_completion(self):
        points = Setpoints()
        initial = points.target_voltage
        points.adjust(soc_delta=5)
        self.assertGreater(points.target_voltage, initial)
        points.reset()
        self.assertEqual(points.target_voltage, initial)
        self.assertFalse(points.target_reached(None))
        self.assertFalse(points.target_reached(79))
        self.assertTrue(points.target_reached(80))
        with self.assertRaises(ValueError):
            points.target_reached(float('nan'))



if __name__ == '__main__':
    unittest.main()
