import sys
import time

from config.settings import settings
from controller.state import ChargerStateMachine


def main():
    print("---------------------------------")
    print(" TREV5 CHARGER")
    print(" By Nikolai Souza & Ethan Wang")
    print("---------------------------------")
    print(f"Python: {sys.version.split()[0]}")

    state_machine = ChargerStateMachine()

    print(f"Initial state: {state_machine.state.name}")
    print("Controller initialized.")
    print("Hardware initialization not yet enabled.")

    try:
        while True:
            time.sleep(settings.loop_interval_s)

    except KeyboardInterrupt:
        print("\nShutting down controller.")


if __name__ == "__main__":
    main()