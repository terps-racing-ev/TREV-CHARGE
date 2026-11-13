"""HVC SOC freshness, reported faults and conservative current limits from the DBC."""
from __future__ import annotations

from dataclasses import dataclass
import time
import math

# DBC extended-frame flag is not part of the on-wire arbitration ID.
SOC_FRAME_ID = 2151678452 & 0x1FFFFFFF
SOC_TIMEOUT_S = 1.0  # Integration default; verify against HVC transmission period.


@dataclass(frozen=True)
class HVCSnapshot:
    soc: float | None = None
    faults: tuple[str, ...] = ()
    current_limit: float | None = None

    @property
    def available(self) -> bool:
        return self.soc is not None


class HVCMonitor:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._soc = None
        self._received_at = None
        self._faults = {}
        self._current_limit = None

    def receive(self, message) -> bool:
        """Accept supported extended HVC data frames.

        Unrelated traffic or malformed frames cannot refresh SOC freshness.
        CAN connection success alone does not establish HVC availability.
        """
        if (not message.is_extended_id or message.is_remote_frame
                or message.is_error_frame or message.dlc != len(message.data)):
            return False
        frame_id = message.arbitration_id
        # IDs and layouts are from dbc/hvc.dbc. Retain each reported fault
        # until a healthy frame of the SAME type arrives; silence cannot clear it.
        lengths = {2151678448 & 0x1FFFFFFF: 7,
                   2151678449 & 0x1FFFFFFF: 5,
                   2151678450 & 0x1FFFFFFF: 0,
                   2151678456 & 0x1FFFFFFF: 8,
                   2151678458 & 0x1FFFFFFF: 1}
        if frame_id in lengths:
            if len(message.data) != lengths[frame_id]:
                return False
            data = message.data
            if frame_id == (2151678448 & 0x1FFFFFFF):
                self._faults['IO'] = ('HVC SDC/IMD/BMS not OK'
                                     if data[0] & 7 != 7 else None)
            elif frame_id == (2151678449 & 0x1FFFFFFF):
                self._faults['BMS'] = ('HVC BMS state/error'
                                      if data[0] not in (1, 2, 3) or data[1] & 0x7F else None)
            elif frame_id == (2151678450 & 0x1FFFFFFF):
                # Panic has no documented clear frame: requires process restart
                # after inspecting the hardware, plus normal operator arming.
                self._faults['PANIC'] = 'HVC panic'
            elif frame_id == (2151678458 & 0x1FFFFFFF):
                self._faults['PL'] = ('HVC protection-line fault'
                                      if data[0] not in (0, 1, 4) else None)
            else:
                # Sign convention is not specified: honor the smaller magnitude
                # until charging direction is confirmed, never assume permission.
                self._current_limit = min(int.from_bytes(data[:4], 'little'),
                                          int.from_bytes(data[4:], 'little')) / 1000
            return True
        if frame_id != SOC_FRAME_ID or len(message.data) != 8:
            return False
        soc = int.from_bytes(message.data[:2], 'little') * 0.01
        if not math.isfinite(soc) or not 0 <= soc <= 100:
            return False
        self._soc = soc
        self._received_at = self._clock()
        return True

    def snapshot(self) -> HVCSnapshot:
        faults = tuple(reason for reason in self._faults.values() if reason)
        unavailable = HVCSnapshot(None, faults, self._current_limit)
        if self._received_at is None:
            return unavailable
        age = self._clock() - self._received_at
        if not 0 <= age < SOC_TIMEOUT_S:
            return unavailable
        return HVCSnapshot(self._soc, faults, self._current_limit)
