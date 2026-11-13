import unittest
from types import SimpleNamespace

from controller.bms import HVCMonitor, HVCSnapshot, SOC_FRAME_ID
from controller.charger import ChargeSession, charging_target
from controller.setpoints import Setpoints


def frame(soc=8000, **overrides):
    fields = dict(arbitration_id=SOC_FRAME_ID, is_extended_id=True,
                  is_remote_frame=False, is_error_frame=False, dlc=8,
                  data=soc.to_bytes(2, 'little') + bytes(6))
    fields.update(overrides)
    return SimpleNamespace(**fields)


class HVCFallbackTests(unittest.TestCase):
    def test_absent_detected_stale_and_recovered(self):
        now = [0.0]
        monitor = HVCMonitor(clock=lambda: now[0])
        points = Setpoints()
        def target():
            return charging_target(points, monitor.snapshot())
        self.assertFalse(target().hvc_available)
        self.assertFalse(target().soc_target_reached)
        self.assertAlmostEqual(target().voltage, 426.60)
        self.assertTrue(monitor.receive(frame()))
        self.assertTrue(target().hvc_available)
        self.assertTrue(target().soc_target_reached)
        self.assertAlmostEqual(target().voltage, 453.6)
        self.assertTrue(target().stop_requested)
        self.assertEqual(target().current, 0)
        now[0] = 1.0
        self.assertFalse(target().hvc_available)
        self.assertIsNone(target().actual_soc)
        self.assertFalse(target().soc_target_reached)
        self.assertAlmostEqual(target().voltage, 426.60)
        self.assertFalse(target().stop_requested)
        monitor.receive(frame(7900))
        self.assertTrue(target().hvc_available)
        self.assertEqual(target().actual_soc, 79)
        self.assertFalse(target().soc_target_reached)
        self.assertAlmostEqual(target().voltage, 453.6)
        self.assertEqual(target().current, points.current)

    def test_soc_overshoot_requests_stop(self):
        target = charging_target(Setpoints(), HVCSnapshot(81))
        self.assertTrue(target.stop_requested)
        self.assertEqual(target.current, 0)

    def test_completion_stays_stopped_until_new_session(self):
        points = Setpoints()
        session = ChargeSession()
        self.assertFalse(session.update(points, HVCSnapshot(79)).stop_requested)
        self.assertTrue(session.update(points, HVCSnapshot(80)).stop_requested)
        for snapshot in (HVCSnapshot(), HVCSnapshot(79)):
            target = session.update(points, snapshot)
            self.assertTrue(target.stop_requested)
            self.assertEqual(target.current, 0)
        session.reset()
        self.assertFalse(session.update(points, HVCSnapshot()).stop_requested)

    def test_invalid_or_unrelated_traffic_does_not_refresh(self):
        now = [0.0]
        monitor = HVCMonitor(clock=lambda: now[0])
        monitor.receive(frame())
        now[0] = 0.9
        for message in (frame(10001), frame(arbitration_id=123),
                        frame(is_extended_id=False), frame(is_remote_frame=True),
                        frame(is_error_frame=True), frame(data=b'\x00'), frame(dlc=7)):
            self.assertFalse(monitor.receive(message))
        now[0] = 1.0
        self.assertFalse(monitor.snapshot().available)
