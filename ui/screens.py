
from dataclasses import dataclass
from PIL import Image, ImageDraw, ImageFont


WIDTH = 128
HEIGHT = 64

# Compact monospace font for the dense 128x64 layout
FONT = ImageFont.truetype("DejaVuSansMono.ttf", 8)


@dataclass
class ScreenData:
    # Operator settings / charger target
    target_voltage: float = 0.0
    target_current: float = 0.0
    target_soc: float = 80.0

    # Actual BMS readings
    actual_voltage: float = 0.0
    actual_current: float = 0.0
    actual_soc: float = 0.0

    # Cell information
    cell_voltage: float = 0.0
    min_cell_voltage: float = 0.0
    max_cell_voltage: float = 0.0

    # Temperature
    min_temp: float = 0.0
    max_temp: float = 0.0

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

    lines = [
        (
            f"Trgt V:{data.target_voltage:.0f} "
            f"I:{data.target_current:.0f} "
            f"S:{data.target_soc:.0f}"
        ),
        (
            f"Actl V:{data.actual_voltage:.0f} "
            f"I:{data.actual_current:.0f} "
            f"S:{data.actual_soc:.0f}"
        ),
        (
            f"{data.cell_voltage:.0f}V "
            f"Mn:{data.min_cell_voltage:.2f} "
            f"Mx:{data.max_cell_voltage:.2f}"
        ),
        (
            f"Temp Min:{data.min_temp:.0f} "
            f"Max:{data.max_temp:.0f}"
        ),
        f"Chrg Time:{minutes:02d}m {seconds:02d}s",
        f"Status:{data.status}",
        f"Error:{data.error}",
    ]

    y_positions = [0, 9, 18, 27, 36, 45, 54]

    for text, y in zip(lines, y_positions):
        draw.text(
            (1, y),
            text,
            font=FONT,
            fill=255,
        )

    return image
