from enum import Enum, auto
import logging


class ChargerState(Enum):
    IDLE = auto()
    READY = auto()
    CHARGING = auto()
    STOPPING = auto()
    FAULT = auto()


class ChargerStateMachine:
    def __init__(self):
        self.state = ChargerState.IDLE

    def transition(self, new_state: ChargerState):
        if self.state == new_state:
            return

        logging.getLogger(__name__).info("State %s -> %s", self.state.name, new_state.name)
        self.state = new_state