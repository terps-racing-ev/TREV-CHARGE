from controller.setpoints import Setpoints
from ui.screens import ScreenData, draw_main_screen

# Testing for screen, might not be fully accurate, made it very quickly.

data = ScreenData(
    target_voltage=Setpoints().target_voltage,
    target_current=15,
    target_soc=80,

    actual_voltage=385,
    actual_current=14,
    actual_soc=64,

    cell_voltage=385,
    min_cell_voltage=3.82,
    max_cell_voltage=3.91,

    min_temp=22,
    max_temp=35,

    charge_seconds=754,

    status="CHARGING",
    error="NONE",
)

image = draw_main_screen(data)

# Enlarge without blurring the pixels
preview = image.resize((768, 384), resample=0)

preview.save("oled_preview.png")
preview.show()
