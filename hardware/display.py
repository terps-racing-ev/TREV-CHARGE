
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1309


class OLEDDisplay:
    def __init__(self, address=0x3C, port=1):
        self.serial = i2c(
            port=port,
            address=address,
        )

        self.device = ssd1309(
            self.serial,
            width=128,
            height=64,
        )

    def show(self, image):
        self.device.display(image)

    def clear(self):
        """clean screen"""
        self.device.clear()
