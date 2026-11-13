"""Charging policy, TC HK-L codec, and fault-latching controller."""
from __future__ import annotations

from dataclasses import dataclass, replace
import logging
import math
import struct
import time
from decimal import Decimal, ROUND_FLOOR
from enum import IntFlag
from controller.state import ChargerState

from config.settings import settings
from controller.battery import soc_to_pack_voltage
from controller.bms import HVCSnapshot
from controller.setpoints import Setpoints


@dataclass(frozen=True)
class ChargingTarget:
    voltage: float
    current: float
    hvc_available: bool
    actual_soc: float | None
    stop_requested: bool
    soc_target_reached: bool
    voltage_stop_threshold: float | None = None
    voltage_target_reached: bool = False


def charging_target(setpoints: Setpoints, hvc: HVCSnapshot) -> ChargingTarget:
    """Prefer fresh HVC SOC; automatically use voltage-only fallback otherwise.

    Fresh HVC SOC selects maximum pack voltage and stops at or above target.
    Without SOC, the rectifier handles taper/termination at the lookup voltage.
    This function does not grant charge permission or clear faults.
    """
    reached = setpoints.target_reached(hvc.soc)
    return ChargingTarget(
        voltage=(soc_to_pack_voltage(100, settings.pack_series)
                 if hvc.available else setpoints.target_voltage),
        current=0.0 if reached else setpoints.current,
        hvc_available=hvc.available,
        actual_soc=hvc.soc,
        stop_requested=reached,
        soc_target_reached=reached,
    )


class ChargeSession:
    """Latch SOC completion until the operator explicitly starts a new session.

    Prevent a telemetry timeout or SOC fluctuation from restarting a completed
    session. This is policy state, not permission to energize hardware.
    """
    def __init__(self):
        self._completed = False

    def reset(self):
        """Call only for a new operator-requested charging session."""
        self._completed = False

    def update(self, setpoints: Setpoints, hvc: HVCSnapshot) -> ChargingTarget:
        target = charging_target(setpoints, hvc)
        self._completed = self._completed or target.soc_target_reached
        if self._completed:
            return replace(target, current=0.0, stop_requested=True)
        return target


# TC HK-L standard protocol 1000, per the project implementation brief.

LOG = logging.getLogger(__name__)
COMMAND_ID = 0x1806E5F4
FEEDBACK_ID = 0x18FF50E5


class ChargerFault(IntFlag):
    HARDWARE = 1
    OVERTEMPERATURE = 2
    AC_INPUT = 4
    BATTERY_CONNECTION = 8
    CAN_TIMEOUT = 16


def encode_command(voltage_v: float, current_a: float, stop: bool = True) -> bytes:
    """Round limits downward to 0.1 units so quantization never raises a limit."""
    def units(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('Command limits must be numeric')
        if not math.isfinite(value) or not 0 <= value <= 6553.5:
            raise ValueError('Command limit outside unsigned 16-bit range')
        return int((Decimal(str(value)) * 10).to_integral_value(rounding=ROUND_FLOOR))
    if type(stop) is not bool:
        raise ValueError('stop must be a boolean')
    return struct.pack('>HHBBBB', units(voltage_v), units(current_a), int(stop), 0, 0, 0)


@dataclass(frozen=True)
class ChargerFeedback:
    raw: bytes
    voltage: float
    current_raw_u16: int
    current_bytes: bytes
    status: int
    current_amps: float | None = None  # Vendor sign-bit meaning unverified.

    @property
    def faults(self):
        return ChargerFault(self.status & 0x1F)

    @property
    def fault_names(self):
        return tuple(flag.name for flag in ChargerFault if flag & self.faults)


def decode_feedback(data: bytes) -> ChargerFeedback:
    if not isinstance(data, (bytes, bytearray)) or len(data) != 8:
        raise ValueError('Feedback must contain exactly eight bytes')
    raw = bytes(data)
    voltage, current = struct.unpack('>HH', raw[:4])
    return ChargerFeedback(raw, voltage / 10, current, raw[2:4], raw[4])


def is_charger_feedback(message) -> bool:
    return (message.arbitration_id == FEEDBACK_ID and message.is_extended_id
            and not message.is_remote_frame and not message.is_error_frame
            and message.dlc == 8 and len(message.data) == 8)


class ChargerController:
    """Single-threaded TC controller; transport is owned/closed by the caller.

    Operator enable is the physical rocker input, not a bypass of fault checks.
    Independent analog SDC protection is external to this software.
    """
    def __init__(self, transport, state_machine, config=settings, clock=time.monotonic):
        self.transport = transport
        self.machine = state_machine
        self.config = config
        self.clock = clock
        self.feedback = None
        self.feedback_at = None
        self.started_at = clock()
        self.last_sent_at = None
        self.last_payload = None
        self.fault_reason = None
        self._off_seen = False
        self._previous_enable = True  # Boot with rocker ON cannot start.
        self._session = ChargeSession()
        self._voltage_completed = False
        self._stop_voltage = config.charger_min_voltage
        self._validate_config()

    def _validate_config(self):
        c = self.config
        if (not all(math.isfinite(v) for v in (
                c.charger_min_voltage, c.charger_max_voltage,
                c.charger_max_current, c.charger_command_period_s,
                c.charger_feedback_timeout_s, c.charger_schedule_timeout_s))
                or not 350 <= c.charger_min_voltage <= c.charger_max_voltage <= 680
                or not 0 < c.charger_max_current <= 14
                or not 0 < c.charger_command_period_s <= 1
                or not c.charger_command_period_s < c.charger_schedule_timeout_s < 5
                or not 1 < c.charger_feedback_timeout_s < 5):
            raise ValueError('Invalid HK-LF-540-14 limits or CAN timing')

    def _send(self, payload):
        self.transport.send(COMMAND_ID, payload, extended=True)
        self.last_payload = payload
        self.last_sent_at = self.clock()
        LOG.debug('TX %08X %s', COMMAND_ID, payload.hex(' '))

    def _stop(self):
        self._send(encode_command(self._stop_voltage, 0, stop=True))

    def fail(self, reason):
        """Latch a fault and attempt immediate STOP, even after a send error."""
        if self.fault_reason != reason:
            self.fault_reason = reason
            LOG.error('Charger inhibited: %s', reason)
        self.machine.transition(ChargerState.FAULT)
        self._off_seen = False
        try:
            self._stop()
        except Exception:
            LOG.exception('Best-effort STOP failed')

    def _receive(self):
        # Bounded nonblocking drain; bus traffic cannot indefinitely delay STOP.
        for _ in range(32):
            message = self.transport.receive(timeout=0.0)
            if message is None:
                break
            if is_charger_feedback(message):
                self.feedback = decode_feedback(message.data)
                self.feedback_at = self.clock()
                LOG.debug('RX %08X %s status=%02X', FEEDBACK_ID,
                          self.feedback.raw.hex(' '), self.feedback.status)
                if self.feedback.faults:
                    self.fail(', '.join(self.feedback.fault_names))

    def _target(self, setpoints, hvc, feedback_fresh):
        target = self._session.update(setpoints, hvc)
        if not hvc.available and target.voltage < self.config.charger_min_voltage:
            threshold = target.voltage
            target = replace(target, voltage=self.config.charger_min_voltage,
                             voltage_stop_threshold=threshold)
            if feedback_fresh and self.feedback.voltage >= threshold:
                self._voltage_completed = True
        if self._voltage_completed:
            target = replace(target, current=0.0, stop_requested=True,
                             voltage_target_reached=True)
        return target

    def _validate_target(self, target, hvc):
        c = self.config
        encode_command(target.voltage, target.current)
        pack_max = soc_to_pack_voltage(100, c.pack_series)
        if not c.charger_min_voltage <= target.voltage <= min(c.charger_max_voltage, pack_max):
            raise ValueError('Voltage outside charger/pack limits')
        if not 0 <= target.current <= min(c.charger_max_current, c.max_current):
            raise ValueError('Current outside charger/pack limits')
        if hvc.current_limit is not None and target.current > hvc.current_limit:
            raise ValueError('Requested current exceeds reported HVC limit')

    def tick(self, setpoints, hvc, operator_enabled=False, *, stop_only=False):
        """Poll feedback, evaluate policy/interlocks, and service command cadence."""
        now = self.clock()
        rising = operator_enabled and not self._previous_enable
        self._previous_enable = operator_enabled
        if stop_only:
            # Bench/startup STOP ticks do not count as observing the real rocker OFF.
            rising = False
            self._previous_enable = True
            self._off_seen = False
        try:
            if self.last_sent_at is None:
                self._stop()  # Always STOP before any possible START.
            elif now - self.last_sent_at >= self.config.charger_schedule_timeout_s:
                self.fail('Missed CAN command deadline')
            self._receive()
            now = self.clock()
            if hvc.faults:
                self.fail('; '.join(hvc.faults))
            feedback_fresh = (self.feedback_at is not None and
                              0 <= now - self.feedback_at < self.config.charger_feedback_timeout_s)
            healthy = feedback_fresh and not self.feedback.faults and not hvc.faults
            if not feedback_fresh and now - self.started_at >= self.config.charger_feedback_timeout_s:
                self.fail('Charger feedback timeout')
            target = self._target(setpoints, hvc, feedback_fresh)
            # Validate even in STOP state; never send an out-of-range request.
            self._validate_target(target, hvc)
            self._stop_voltage = target.voltage
            if not operator_enabled:
                self._off_seen = not stop_only
                if self.machine.state != ChargerState.FAULT:
                    self.machine.transition(ChargerState.IDLE)
            elif rising and self._off_seen and healthy and not stop_only:
                self.fault_reason = None
                self._off_seen = False
                self._session.reset()
                self._voltage_completed = False
                target = self._target(setpoints, hvc, feedback_fresh)
                self._validate_target(target, hvc)
                self.machine.transition(ChargerState.READY)
                self.machine.transition(ChargerState.CHARGING)
            stop = (stop_only or not operator_enabled or not healthy
                    or self.fault_reason is not None or target.stop_requested
                    or target.current <= 0 or self.machine.state != ChargerState.CHARGING)
            if stop and self.machine.state == ChargerState.CHARGING:
                self.machine.transition(ChargerState.STOPPING)
            payload = encode_command(target.voltage, 0 if stop else target.current, stop)
            if payload != self.last_payload or now - self.last_sent_at >= self.config.charger_command_period_s:
                self._send(payload)
            return target
        except Exception as exc:
            self.fail(str(exc))
            return None

    def shutdown(self):
        if self.machine.state != ChargerState.FAULT:
            self.machine.transition(ChargerState.STOPPING)
        try:
            self._stop()
        except Exception:
            LOG.exception('Shutdown STOP failed')
        if self.machine.state != ChargerState.FAULT:
            self.machine.transition(ChargerState.IDLE)
