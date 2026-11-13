from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from PIL import Image, ImageDraw, ImageFont


WIDTH = 128
HEIGHT = 64

# FONT IN ASSETS!!!!!!!!!!
FONT_PATH = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "adafruits-gfx-library-default-font.ttf"
)

FONT = ImageFont.truetype(str(FONT_PATH), size=8)


@dataclass
class ScreenData:
    # Operator settings / charger target
    target_voltage: float = 0.0
    target_current: float = 0.0
    target_soc: float = 80.0
    voltage_stop_threshold: float | None = None

    hvc_available: bool = False  # Runtime detection, not an operator setting

    # Actual readings; None means unavailable, never a measured zero.
    actual_voltage: float | None = None
    actual_current: float | None = None
    actual_soc: float | None = None

    # Cell information
    cell_voltage: float | None = None
    min_cell_voltage: float | None = None
    max_cell_voltage: float | None = None

    # Temperature
    min_temp: float | None = None
    max_temp: float | None = None

    # Charge elapsed time
    charge_seconds: int = 0

    # Status and errors
    status: str = "IDLE"
    error: str = "NONE"


def draw_main_screen(data: ScreenData) -> Image.Image:
    """Render the charger status screen as a 128x64 image."""

    image = Image.new("1", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(image)

    minutes, seconds = divmod(
        max(0, data.charge_seconds), 60
    )

    def value(number, digits=0):
        return "--" if number is None else f"{number:.{digits}f}"

    lines = [
        (
            f">>Target   "
            f"I:{data.target_current:.0f} "
            f"S:{data.target_soc:.0f}%"
        ),
        (
            f"Actl V:{value(data.actual_voltage, 0)} "
            f"I:{value(data.actual_current, 0)} "
            f"S:{value(data.actual_soc, 0)}%"
        ),
        (
            f"{value(data.cell_voltage, 0)}V "
            f"Mn:{value(data.min_cell_voltage, 2)} "
            f"Mx:{value(data.max_cell_voltage, 2)}"
        ),
        (
            f"Temp Min:{value(data.min_temp, 0)} "
            f"Max:{value(data.max_temp, 0)}"
        ),
        f"Charge Time:{minutes:02d}m {seconds:02d}s",
        f"Status:{data.status}",
        f"Error:{data.error}",
    ]

    if not data.hvc_available:
        lines[1] = f"V:{value(data.actual_voltage)} I:{value(data.actual_current)} S:--"
        lines[2] = (f"Stop at:{data.voltage_stop_threshold:.1f}V"
                    if data.voltage_stop_threshold is not None
                    else f"Est Target:{data.target_voltage:.1f}V")
        lines[3] = "HVC LOST/WAITING"

    y_positions = [0, 9, 18, 27, 36, 45, 54]

    for text, y in zip(lines, y_positions):
        draw.text(
            (1, y),
            text,
            font=FONT,
            fill=255,
        )

    return image
