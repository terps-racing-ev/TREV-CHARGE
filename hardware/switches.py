from gpiozero import Button
from config.pins import ROCKER_SWITCH

class Switches:
    def __init__(self):
        self.rocker = Button(
            ROCKER_SWITCH,
            pull_up=True,
            bounce_time=0.05,
        )

    @property
    def enabled(self) -> bool:
        return self.rocker.is_pressed

    def close(self):
        self.rocker.close()