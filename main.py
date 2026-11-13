"""TREV charger entry point. Default is offline; hardware requires an explicit mode."""
import argparse
import logging
import time

from config.settings import settings
from controller.bms import HVCMonitor
from controller.charger import ChargeSession, ChargerController
from controller.state import ChargerStateMachine
from controller.setpoints import Setpoints

LOG = logging.getLogger(__name__)


def run_hardware(*, stop_only=False):
    # Delay platform dependencies so offline mode and pure tests work off-Pi.
    from hardware.can_bus import CANInterface

    if settings.can_bms_interface == settings.can_charger_interface:
        raise ValueError('HVC and charger must use separate CAN interfaces')
    charger_bus = CANInterface(settings.can_charger_interface)
    hvc_bus = CANInterface(settings.can_bms_interface)
    controller = None
    encoders = switches = display = None
    points = Setpoints()
    hvc = HVCMonitor()
    machine = ChargerStateMachine()
    next_hvc_retry = 0.0
    next_display = 0.0
    try:
        charger_bus.connect()
        controller = ChargerController(charger_bus, machine)
        # Establish STOP before initializing any other hardware.
        controller.tick(points, hvc.snapshot(), stop_only=True)
        if not stop_only:
            from hardware.encoders import Encoders
            from hardware.switches import Switches
            from hardware.display import OLEDDisplay
            from ui.screens import ScreenData, draw_main_screen
            switches = Switches()
            encoders = Encoders()
            display = OLEDDisplay()
        while True:
            now = time.monotonic()
            if hvc_bus.bus is None and now >= next_hvc_retry:
                next_hvc_retry = now + 5.0
                try:
                    hvc_bus.connect()
                except Exception as exc:
                    LOG.warning('HVC CAN unavailable; voltage fallback: %s', exc)
            if hvc_bus.bus is not None:
                try:
                    for _ in range(32):
                        message = hvc_bus.receive(timeout=0.0)
                        if message is None:
                            break
                        hvc.receive(message)
                except Exception as exc:
                    LOG.warning('HVC receive failed; retaining faults: %s', exc)
                    hvc_bus.close()
            if encoders is not None:
                points.adjust(*encoders.read_deltas())
            snapshot = hvc.snapshot()
            target = controller.tick(points, snapshot,
                                     switches.enabled if switches else False,
                                     stop_only=stop_only)
            if display is not None and now >= next_display:
                next_display = now + 1 / settings.ui_refresh_hz
                feedback = controller.feedback
                fresh = (controller.feedback_at is not None and
                         now - controller.feedback_at < settings.charger_feedback_timeout_s)
                data = ScreenData(
                    target_voltage=target.voltage if target else 0,
                    target_current=target.current if target else 0,
                    target_soc=points.target_soc,
                    voltage_stop_threshold=target.voltage_stop_threshold if target else None,
                    hvc_available=snapshot.available,
                    actual_soc=snapshot.soc,
                    actual_voltage=feedback.voltage if feedback and fresh else None,
                    actual_current=None,  # TC current sign convention unverified.
                    status=machine.state.name,
                    error='FAULT' if controller.fault_reason else 'NONE',
                )
                display.show(draw_main_screen(data))
            time.sleep(settings.loop_interval_s)
    except KeyboardInterrupt:
        LOG.info('Operator shutdown')
    except Exception as exc:
        LOG.exception('Hardware loop stopped')
        if controller is not None:
            controller.fail(str(exc))
    finally:
        if controller is not None:
            controller.shutdown()
        # A failed cleanup must not prevent the remaining resources closing.
        for resource in (charger_bus, hvc_bus, encoders, switches):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    LOG.exception('Resource cleanup failed')
        if display is not None:
            try:
                display.clear()
            except Exception:
                LOG.exception('Display cleanup failed')


def main():
    parser = argparse.ArgumentParser(description='TREV5 TC HK-LF-540-14 controller')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--stop-only', action='store_true', help='CAN bench mode: never send START')
    modes.add_argument('--hardware', action='store_true', help='Run with physical rocker, encoders and OLED')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    print('TREV5 CHARGER — HK-LF-540-14')
    if args.hardware or args.stop_only:
        run_hardware(stop_only=args.stop_only)
    else:
        points = Setpoints()
        target = ChargeSession().update(points, HVCMonitor().snapshot())
        print(f'Offline: target {points.target_soc}% / {target.voltage:.2f} V / {target.current:.1f} A')
        print('No hardware opened. Use --stop-only for CAN bench checks.')


if __name__ == '__main__':
    main()
