import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from config.settings import settings
from controller.bms import HVCMonitor, HVCSnapshot, SOC_FRAME_ID
from controller.charger import (
    ChargerController, ChargerFault, COMMAND_ID, FEEDBACK_ID,
    decode_feedback, encode_command, is_charger_feedback,
)
from controller.setpoints import Setpoints
from controller.state import ChargerState, ChargerStateMachine


def message(data=bytes.fromhex('0F A0 00 14 00 00 00 00'), **overrides):
    fields = dict(arbitration_id=FEEDBACK_ID, data=data, dlc=len(data),
                  is_extended_id=True, is_remote_frame=False, is_error_frame=False)
    fields.update(overrides)
    return SimpleNamespace(**fields)


class Bus:
    def __init__(self):
        self.incoming = []
        self.sent = []
        self.fail_send = False
        self.fail_receive = False

    def send(self, arbitration_id, data, *, extended=False):
        if self.fail_send:
            self.fail_send = False
            raise OSError('simulated CAN send error')
        self.sent.append((arbitration_id, data, extended))

    def receive(self, timeout=0):
        if self.fail_receive:
            raise OSError('simulated receive failure')
        return self.incoming.pop(0) if self.incoming else None


class CodecTests(unittest.TestCase):
    def test_exact_commands(self):
        self.assertEqual(encode_command(400, 2), bytes.fromhex('0F A0 00 14 01 00 00 00'))
        self.assertEqual(encode_command(400, 2, False), bytes.fromhex('0F A0 00 14 00 00 00 00'))
        self.assertEqual(encode_command(400.09, 2.09), encode_command(400, 2))

    def test_invalid_commands(self):
        for value in (-1, 6553.6, float('nan'), float('inf'), True, '400', None):
            with self.subTest(value=value):
                for args in ((value, 2), (400, value)):
                    with self.assertRaises(ValueError):
                        encode_command(*args)
        with self.assertRaises(ValueError):
            encode_command(400, 2, stop=0)

    def test_feedback_flags_and_raw_current(self):
        for status in (0, 1, 2, 4, 8, 16, 31, 128, 255):
            data = bytes.fromhex('0F A0 80 14') + bytes([status, 0, 0, 0])
            feedback = decode_feedback(data)
            self.assertEqual(feedback.voltage, 400)
            self.assertEqual(feedback.current_raw_u16, 0x8014)
            self.assertEqual(feedback.current_bytes, b'\x80\x14')
            self.assertIsNone(feedback.current_amps)
            self.assertEqual(feedback.raw, data)
            self.assertEqual(feedback.faults, ChargerFault(status & 31))
            self.assertEqual(len(feedback.fault_names), bin(status & 31).count('1'))
        for data in (bytes(7), bytes(9), '12345678'):
            with self.assertRaises(ValueError):
                decode_feedback(data)

    def test_frame_filtering(self):
        self.assertTrue(is_charger_feedback(message()))
        for override in (dict(arbitration_id=1), dict(is_extended_id=False),
                         dict(is_remote_frame=True), dict(is_error_frame=True),
                         dict(dlc=7), dict(data=bytes(7))):
            self.assertFalse(is_charger_feedback(message(**override)))


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.bus = Bus()
        self.machine = ChargerStateMachine()
        self.points = Setpoints()
        self.control = ChargerController(self.bus, self.machine, clock=lambda: self.now)

    def tick(self, enabled=False, hvc=HVCSnapshot(), fresh=True, stop_only=False):
        if fresh:
            self.bus.incoming.append(message())
        return self.control.tick(self.points, hvc, enabled, stop_only=stop_only)

    def assert_stop(self):
        self.assertEqual(self.bus.sent[-1][1][4], 1)
        self.assertEqual(self.bus.sent[-1][1][2:4], b'\x00\x00')

    def arm(self, hvc=HVCSnapshot()):
        self.tick(False, hvc)
        self.tick(True, hvc)
        self.assertEqual(self.machine.state, ChargerState.CHARGING)

    def test_startup_on_does_not_start_and_frames_extended(self):
        self.tick(True)
        self.tick(True)
        self.assert_stop()
        self.assertEqual(self.machine.state, ChargerState.IDLE)
        self.assertTrue(all(item[0] == COMMAND_ID and item[2] and len(item[1]) == 8
                            for item in self.bus.sent))
        self.arm()
        self.assertEqual(self.bus.sent[-1][1][4], 0)

    def test_stop_only_cannot_start(self):
        self.tick(False, stop_only=True)
        self.tick(True, stop_only=True)
        self.assert_stop()

    def test_startup_stop_tick_cannot_arm_an_already_on_rocker(self):
        self.tick(False, stop_only=True)
        self.tick(True)
        self.assert_stop()
        self.assertEqual(self.machine.state, ChargerState.IDLE)
        self.arm()

    def test_hvc_loss_changes_voltage_without_stopping(self):
        self.arm(HVCSnapshot(79))
        self.assertEqual(self.bus.sent[-1][1][:2], (4536).to_bytes(2, 'big'))
        self.tick(True)
        self.assertEqual(self.bus.sent[-1][1][:2], (4266).to_bytes(2, 'big'))
        self.assertEqual(self.bus.sent[-1][1][4], 0)
        self.tick(True, HVCSnapshot(79))
        self.assertEqual(self.bus.sent[-1][1][:2], (4536).to_bytes(2, 'big'))

    def test_soc_stop_survives_hvc_loss_and_requires_new_session(self):
        self.arm(HVCSnapshot(79))
        self.tick(True, HVCSnapshot(81))
        self.assert_stop()
        self.tick(True)
        self.assert_stop()
        self.arm()

    def test_fault_latches_even_if_next_frame_is_healthy(self):
        self.arm()
        self.bus.incoming.append(message(bytes.fromhex('0F A0 00 00 01 00 00 00')))
        with self.assertLogs('controller.charger', level='ERROR'):
            self.tick(True)  # Healthy frame follows fault in same queue.
        self.assert_stop()
        self.assertEqual(self.machine.state, ChargerState.FAULT)
        self.tick(True)
        self.assert_stop()
        self.arm()

    def test_hvc_fault_inhibits_and_requires_clear_plus_rearm(self):
        self.arm()
        with self.assertLogs('controller.charger', level='ERROR'):
            self.tick(True, HVCSnapshot(None, ('SDC open',)))
        self.assert_stop()
        self.tick(True)
        self.assert_stop()
        self.arm()

    def test_feedback_timeout_despite_unrelated_frames(self):
        self.arm()
        for when in (1, 2, 3):
            self.now = when
            self.bus.incoming.append(message(arbitration_id=123))
            if when == 3:
                with self.assertLogs('controller.charger', level='ERROR'):
                    self.tick(True, fresh=False)
            else:
                self.tick(True, fresh=False)
        self.assert_stop()
        self.assertEqual(self.machine.state, ChargerState.FAULT)

    def test_no_feedback_no_start(self):
        self.tick(False, fresh=False)
        self.tick(True, fresh=False)
        self.assert_stop()
        self.tick(True)  # Feedback returning cannot arm without another edge.
        self.assert_stop()

    def test_periodic_stop_and_missed_schedule(self):
        self.tick()
        count = len(self.bus.sent)
        self.now = 0.9
        self.tick()
        self.assertEqual(len(self.bus.sent), count)
        self.now = 1
        self.tick()
        self.assertEqual(len(self.bus.sent), count + 1)
        self.now = 3
        with self.assertLogs('controller.charger', level='ERROR'):
            self.tick(True)
        self.assert_stop()
        self.assertEqual(self.machine.state, ChargerState.FAULT)

    def test_send_and_receive_failure(self):
        self.arm()
        self.bus.fail_send = True
        self.now = 1
        with self.assertLogs('controller.charger', level='ERROR'):
            self.tick(True)
        self.assert_stop()  # Retry after failed START is STOP.
        self.assertEqual(self.machine.state, ChargerState.FAULT)
        self.bus.fail_receive = True
        with self.assertLogs('controller.charger', level='ERROR'):
            self.tick(True)
        self.assert_stop()

    def test_limits_reject_instead_of_clamp(self):
        for soc, current, hvc in ((101, 8, HVCSnapshot()), (80, 15, HVCSnapshot()),
                                   (80, 8, HVCSnapshot(70, (), 5))):
            with self.subTest(soc=soc, current=current):
                self.points.target_soc = soc
                self.points.current = current
                with self.assertLogs('controller.charger', level='ERROR'):
                    self.tick(False, hvc)
                self.assert_stop()
                self.assertEqual(self.machine.state, ChargerState.FAULT)
        with self.assertRaises(ValueError):
            ChargerController(self.bus, self.machine,
                              replace(settings, charger_max_voltage=700))

    def low_tick(self, enabled, voltage, hvc=HVCSnapshot()):
        data = int(round(voltage * 10)).to_bytes(2, 'big') + bytes(6)
        self.bus.incoming.append(message(data))
        return self.tick(enabled, hvc, fresh=False)

    def test_low_fallback_voltage_cutoff_and_latch(self):
        self.points.target_soc = 10  # 340.2 V lookup, below the 350 V command floor.
        self.low_tick(False, 330)
        target = self.low_tick(True, 330)
        self.assertEqual(target.voltage, 350)
        self.assertAlmostEqual(target.voltage_stop_threshold, 340.2)
        self.assertEqual(self.bus.sent[-1][1][:2], (3500).to_bytes(2, 'big'))
        self.assertEqual(self.bus.sent[-1][1][4], 0)
        self.assertIsNone(self.control.fault_reason)
        target = self.low_tick(True, 340.2)
        self.assert_stop()
        self.assertTrue(target.voltage_target_reached)
        self.assertFalse(target.soc_target_reached)
        self.low_tick(True, 330, HVCSnapshot(4))
        self.assert_stop()  # HVC recovery and voltage relaxation cannot restart.
        self.low_tick(False, 330)
        self.low_tick(True, 330)
        self.assertEqual(self.bus.sent[-1][1][4], 0)

    def test_low_fallback_already_above_target_never_starts(self):
        self.points.target_soc = 0
        self.low_tick(False, 300)
        self.low_tick(True, 300)
        self.assertTrue(all(data[4] == 1 for _, data, _ in self.bus.sent))
        self.assertIsNone(self.control.fault_reason)

    def test_low_fallback_missing_or_stale_feedback_stops(self):
        self.points.target_soc = 10
        self.tick(False, fresh=False)
        self.tick(True, fresh=False)
        self.assert_stop()
        self.low_tick(False, 330)
        self.low_tick(True, 330)
        for when in (1, 2):
            self.now = when
            self.tick(True, fresh=False)
        self.now = 3
        with self.assertLogs('controller.charger', level='ERROR'):
            self.tick(True, fresh=False)
        self.assert_stop()
        self.assertEqual(self.machine.state, ChargerState.FAULT)

    def test_hvc_loss_at_low_target_stops_on_voltage(self):
        self.points.target_soc = 10
        self.arm(HVCSnapshot(4))
        self.assertEqual(self.bus.sent[-1][1][:2], (4536).to_bytes(2, 'big'))
        target = self.low_tick(True, 346)
        self.assert_stop()
        self.assertTrue(target.voltage_target_reached)
        self.assertIsNone(self.control.fault_reason)

    def test_normal_fallback_leaves_taper_to_rectifier(self):
        self.low_tick(False, 430)
        target = self.low_tick(True, 430)
        self.assertIsNone(target.voltage_stop_threshold)
        self.assertFalse(target.voltage_target_reached)
        self.assertEqual(self.bus.sent[-1][1][4], 0)

    def test_feedback_uses_time_after_receive(self):
        times = [0.0]
        def clock():
            times[0] += 0.001
            return times[0]
        self.control = ChargerController(self.bus, self.machine, clock=clock)
        self.arm()
        self.tick(True)
        self.assertEqual(self.machine.state, ChargerState.CHARGING)

    def test_shutdown_and_operator_off(self):
        self.arm()
        self.tick(False)
        self.assert_stop()
        self.arm()
        self.control.shutdown()
        self.assert_stop()
        self.assertEqual(self.machine.state, ChargerState.IDLE)


class HVCFaultTests(unittest.TestCase):
    def test_sdc_fault_retained_without_soc(self):
        hvc = HVCMonitor()
        io_id = 2151678448 & 0x1FFFFFFF
        self.assertTrue(hvc.receive(message(bytes(7), arbitration_id=io_id)))
        self.assertTrue(hvc.snapshot().faults)
        self.assertFalse(hvc.snapshot().available)
        hvc.receive(message(b'\x07' + bytes(6), arbitration_id=io_id))
        self.assertFalse(hvc.snapshot().faults)

    def test_bms_errors_and_panic(self):
        hvc = HVCMonitor()
        state_id = 2151678449 & 0x1FFFFFFF
        for bit in range(7):
            hvc.receive(message(bytes([2, 1 << bit, 0, 0, 0]), arbitration_id=state_id))
            self.assertTrue(hvc.snapshot().faults)
        hvc.receive(message(bytes([2, 0, 0, 0, 0]), arbitration_id=state_id))
        self.assertFalse(hvc.snapshot().faults)
        hvc.receive(message(b'', arbitration_id=2151678450 & 0x1FFFFFFF))
        hvc.receive(message(bytes([2, 0, 0, 0, 0]), arbitration_id=state_id))
        self.assertIn('HVC panic', hvc.snapshot().faults)

    def test_protection_line_fault(self):
        hvc = HVCMonitor()
        for reason in (2, 3, 255):
            hvc.receive(message(bytes([reason]), arbitration_id=2151678458 & 0x1FFFFFFF))
            self.assertTrue(hvc.snapshot().faults)
        hvc.receive(message(bytes([4]), arbitration_id=2151678458 & 0x1FFFFFFF))
        self.assertFalse(hvc.snapshot().faults)

    def test_current_limit_preserved(self):
        hvc = HVCMonitor()
        data = (5000).to_bytes(4, 'little') + (10000).to_bytes(4, 'little')
        hvc.receive(message(data, arbitration_id=2151678456 & 0x1FFFFFFF))
        self.assertEqual(hvc.snapshot().current_limit, 5)


class IntegrationTests(unittest.TestCase):
    def test_missing_can_hardware_closes_without_start(self):
        import main
        instances = []
        class MissingCAN:
            def __init__(self, channel):
                self.closed = False
                instances.append(self)
            def connect(self):
                raise OSError('CAN interface absent')
            def close(self):
                self.closed = True
        with patch.dict('sys.modules', {'hardware.can_bus': SimpleNamespace(CANInterface=MissingCAN)}):
            with self.assertLogs('main', level='ERROR'):
                main.run_hardware(stop_only=True)
        self.assertTrue(all(bus.closed for bus in instances))

    def test_virtual_bus_stop_transport_and_feedback(self):
        try:
            import can
        except ImportError:
            self.skipTest('python-can is installed in the project virtualenv')
        from hardware.can_bus import CANInterface
        import uuid
        channel = str(uuid.uuid4())
        adapter = CANInterface(channel)
        adapter.bus = can.Bus(interface='virtual', channel=channel)
        peer = can.Bus(interface='virtual', channel=channel)
        controller = ChargerController(adapter, ChargerStateMachine())
        try:
            peer.send(can.Message(arbitration_id=FEEDBACK_ID, is_extended_id=True,
                                  data=bytes.fromhex('0F A0 80 14 00 00 00 00')))
            controller.tick(Setpoints(), HVCSnapshot(), stop_only=True)
            frames = []
            while True:
                frame = peer.recv(timeout=0)
                if frame is None:
                    break
                frames.append(frame)
            self.assertTrue(frames)
            self.assertTrue(all(frame.is_extended_id and frame.dlc == 8
                                and frame.arbitration_id == COMMAND_ID
                                and frame.data[4] == 1 for frame in frames))
            self.assertEqual(controller.feedback.voltage, 400)
            self.assertIsNone(controller.feedback.current_amps)
            controller.shutdown()
            self.assertEqual(peer.recv(timeout=0.1).data[4], 1)
        finally:
            adapter.close()
            peer.shutdown()


if __name__ == '__main__':
    unittest.main()
