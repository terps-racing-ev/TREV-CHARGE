
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Battery configuration
    pack_series: int = 108
    pack_parallel: int = 3

    # Default charging settings
    default_soc: int = 80
    default_current: float = 8.0

    # Operator-adjustable limits
    min_soc: int = 0
    max_soc: int = 100

    min_current: float = 0.0
    max_current: float = 14.0

    # Rotary encoder increments
    soc_step: int = 1
    current_step: float = 0.5

    # CAN interfaces
    can_bms_interface: str = "can0"
    can_charger_interface: str = "can1"

    can_bms_bitrate: int = 500_000
    can_charger_bitrate: int = 250_000

    # OLED display
    oled_width: int = 128
    oled_height: int = 64

    # Main application
    ui_refresh_hz: int = 5
    loop_interval_s: float = 0.05


settings = Settings()
