"""User-supplied SOC voltage targets for the RS50 configuration. See docs/rs50-soc-voltage.md.

The supplied chart has not been independently validated as RS50 OCV data.
They support scaffold/bench development, not SOC measurement or protection.
"""

import math


RS50_MAX_CELL_VOLTAGE = 4.20
# (SOC percent, cell volts), transcribed from the user-supplied chart.
# Storage endpoints confirmed by the user: 30% = 3.46 V, 35% = 3.52 V.
RS50_SOC_VOLTAGE_TABLE = (
    (0.0, 2.50),
    (10.0, 3.15),
    (20.0, 3.35),
    (30.0, 3.46),
    (35.0, 3.52),
    (40.0, 3.56),
    (50.0, 3.65),
    (60.0, 3.76),
    (70.0, 3.85),
    (80.0, 3.95),
    (90.0, 4.06),
    (100.0, RS50_MAX_CELL_VOLTAGE),
)


def soc_to_cell_voltage(soc: float) -> float:
    """Interpolate the user-supplied voltage target for SOC in [0, 100].

    Reject invalid inputs instead of silently producing a charging target.
    """
    if isinstance(soc, bool) or not isinstance(soc, (int, float)):
        raise ValueError("SOC must be a finite number in [0, 100]")
    if not math.isfinite(soc) or not 0 <= soc <= 100:
        raise ValueError("SOC must be a finite number in [0, 100]")
    for (s0, v0), (s1, v1) in zip(
        RS50_SOC_VOLTAGE_TABLE, RS50_SOC_VOLTAGE_TABLE[1:]
    ):
        if soc <= s1:
            return v0 + (v1 - v0) * (soc - s0) / (s1 - s0)
    return RS50_MAX_CELL_VOLTAGE


def soc_to_pack_voltage(soc: float, series_cells: int) -> float:
    """Scale by series count only; parallel count does not affect voltage."""
    if type(series_cells) is not int or series_cells <= 0:
        raise ValueError("Series cell count must be a positive integer")
    return soc_to_cell_voltage(soc) * series_cells
