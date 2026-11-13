from __future__ import annotations

import math

from config.settings import settings
from controller.battery import soc_to_cell_voltage, soc_to_pack_voltage

class Setpoints:
    def __init__(self):
        self.target_soc = settings.default_soc
        self.current = settings.default_current

        self._validate()

    def _validate(self):
        if not (
            settings.min_soc <= self.target_soc <= settings.max_soc
        ):
            raise ValueError("Default SOC outside limits")

        if not (
            settings.min_current <= self.current <= settings.max_current
        ):
            raise ValueError("Default current outside limits")

        if settings.soc_step <= 0 or settings.current_step <= 0:
            raise ValueError("Encoder steps must be positive")

    @staticmethod
    def _clamp(value, minimum, maximum):
        return max(minimum, min(value, maximum))

    @property
    def target_cell_voltage(self) -> float:
        return soc_to_cell_voltage(self.target_soc)

    @property
    def target_voltage(self) -> float:
        """Provisional pack CV target; recalculated after every SOC adjustment."""
        return soc_to_pack_voltage(self.target_soc, settings.pack_series)

    def adjust(self, soc_delta=0, current_delta=0):
        """Adjust setpoints using rotary encoder movements."""

        self.target_soc = self._clamp(
            self.target_soc + soc_delta * settings.soc_step,
            settings.min_soc,
            settings.max_soc,
        )

        self.current = self._clamp(
            self.current + current_delta * settings.current_step,
            settings.min_current,
            settings.max_current,
        )

        # Avoid floating-point rounding artifacts
        self.current = round(self.current, 2)

    def target_reached(self, bms_soc: float | None) -> bool:
        """Return True when valid BMS SOC reaches target."""

        if bms_soc is None:
            return False

        if not math.isfinite(bms_soc):
            raise ValueError("Invalid BMS SOC")

        if not 0 <= bms_soc <= 100:
            raise ValueError("BMS SOC outside valid range")

        return bms_soc >= self.target_soc

    def reset(self):
        """Restore default operator settings."""
        self.target_soc = settings.default_soc
        self.current = settings.default_current
