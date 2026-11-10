from config.settings import settings


class Setpoints:
    def __init__(
        self,
        target_soc: int,
        current: float,
        current_min: float,
        current_max: float,
    ):
        if current_min > current_max:
            raise ValueError("Invalid current limits")

        self.target_soc = max(0, min(100, target_soc))

        self.current_min = current_min
        self.current_max = current_max

        self.current = max(
            current_min,
            min(current, current_max)
        )

    def adjust(self, soc_delta=0, current_delta=0):
        self.target_soc = max(
            0,
            min(
                100,
                self.target_soc + soc_delta * settings.soc_step
            )
        )

        self.current = max(
            self.current_min,
            min(
                self.current_max,
                self.current + current_delta * settings.current_step
            )
        )

    def target_reached(self, bms_soc: float) -> bool:
        return bms_soc >= self.target_soc