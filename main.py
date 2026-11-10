
import sys
import time

from config.settings import settings
from controller.state import ChargerStateMachine
from controller.setpoints import Setpoints


def main():
    print("---------------------------------")
    print(" TREV5 CHARGER")
    print(" By Nikolai Souza & Ethan Wang")
    print("---------------------------------")
    print(f"Python: {sys.version.split()[0]}")

    # Initialize controller state
    state_machine = ChargerStateMachine()

    # Initialize operator setpoints
    setpoints = Setpoints()

    print(f"Initial state: {state_machine.state.name}")
    print()
    print("Charging Configuration:")
    print(f"  Battery: {settings.pack_series}S{settings.pack_parallel}P")
    print(f"  Target SOC: {setpoints.target_soc}%")
    print(f"  Requested Current: {setpoints.current:.1f} A")
    print(f"  Maximum Current: {settings.max_current:.1f} A")
    print()
    print(f"  BMS CAN: {settings.can_bms_bitrate:,} bit/s")
    print(f"  Charger CAN: {settings.can_charger_bitrate:,} bit/s")

    print("\nController initialized.")
    print("Hardware initialization not yet enabled.")
    print("Press Ctrl+C to exit.\n")

    try:
        while True:
            # TODO:
            # 1. read rocker switch and rotary encoders
            # 2. receive bms telemetry
            # 3. set or update charger state
            # 4. read and send validated can commands
            # 5. update the oled screen

            time.sleep(settings.loop_interval_s)

    except KeyboardInterrupt:
        print("\nShutting down controller.")


if __name__ == "__main__":
    main()
