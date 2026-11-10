
from gpiozero import RotaryEncoder

from config.pins import (
    SOC_ENCODER_A,
    SOC_ENCODER_B,
    CURRENT_ENCODER_A,
    CURRENT_ENCODER_B,
)


class Encoders:
    def __init__(self):
        # Encoder 1: Target State of Charge (%)
        self.soc = RotaryEncoder(
            SOC_ENCODER_A,
            SOC_ENCODER_B,
            max_steps=0,
            wrap=False,
        )

        # Encoder 2: Charging Current (A)
        self.current = RotaryEncoder(
            CURRENT_ENCODER_A,
            CURRENT_ENCODER_B,
            max_steps=0,
            wrap=False,
        )

        # Track previously read positions
        self._last_soc_steps = self.soc.steps
        self._last_current_steps = self.current.steps

    def read_soc_delta(self) -> int:
        """Return SOC encoder movement since last read."""
        steps = self.soc.steps
        delta = steps - self._last_soc_steps
        self._last_soc_steps = steps
        return delta

    def read_current_delta(self) -> int:
        """Return current encoder movement since last read."""
        steps = self.current.steps
        delta = steps - self._last_current_steps
        self._last_current_steps = steps
        return delta

    def read_deltas(self) -> tuple[int, int]:
        """Return (SOC delta, current delta)."""
        return (
            self.read_soc_delta(),
            self.read_current_delta(),
        )

    def close(self):
        """Release GPIO resources."""
        self.soc.close()
        self.current.close()
