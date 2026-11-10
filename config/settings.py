from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # CAN interfaces
    can_bms_interface: str = "can0"
    can_charger_interface: str = "can1"

    can_bms_bitrate: int = 500_000
    can_charger_bitrate: int = 250_000

    # OLED
    oled_width: int = 128
    oled_height: int = 64

    # Encoder adjustment
    soc_step: int = 1         # Percentage points
    current_step: float = 0.5 # Amps

    # User interface
    ui_refresh_hz: int = 5
    loop_interval_s: float = 0.05


settings = Settings()