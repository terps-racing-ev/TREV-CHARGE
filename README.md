# TREV-CHARGE

Raspberry Pi controller for the Terps Racing EV charger: physical SOC/current
inputs, OLED, HVC CAN monitoring, and TC HK-LF-540-14 standard protocol 1000.

## Charging behavior

| HVC SOC | Requested voltage | Termination |
| --- | --- | --- |
| Fresh (less than 1 second old) | 4.20 V × series count; 453.6 V at 108S | SOC >= target requests STOP; completion stays latched until a new session |
| Missing/stale, lookup >= 350 V | RS50 lookup voltage; 426.60 V at 80%, sent as 426.6 V | Rectifier handles CV taper and termination |
| Missing/stale, lookup < 350 V | 350 V command; lookup retained as a separate stop threshold | Fresh charger voltage >= lookup threshold latches STOP |

Requested current is bounded by the operator limit (14 A), charger rating, and
any received HVC current limit. Voltage is bounded by both charger and pack.
HK-LF-540-14 limits are 350–680 V / 14 A. Commands outside these limits fault. For a low-SOC fallback lookup below 350 V,
the controller explicitly requests 350 V and monitors charger-reported voltage
against the lower lookup threshold. For example, 10% means a 350 V CAN command
and STOP at reported voltage >= 340.2 V. The OLED shows `Stop at:340.2V`.
If already at/above the threshold, START is inhibited. Completion stays latched
through voltage relaxation or HVC recovery until an operator OFF/ON cycle.
Missing/stale charger feedback still inhibits charging/faults as before.

This edge mode uses a software voltage cutoff, not CV taper at the lower target.
Feedback and STOP latency can produce overshoot; it does not verify actual SOC.
The charger must be bench-verified to measure connected battery voltage while
stopped and operate correctly with a battery below its specified output range.
A 350 V command alone does not establish that hardware capability.

The [RS50 table](docs/rs50-soc-voltage.md) now follows the user-supplied chart, with linear
interpolation between its points. It has not been independently validated as an
RS50 calibration. The user confirmed the storage endpoints: 30% = 3.46 V and 35% = 3.52 V.

Per the owner's clarification, the analog SDC independently protects the system
without HVC CAN. The Pi does not measure or certify that circuit. This supersedes
the brief's assumption that live BMS CAN permission is always required. Loss of
HVC SOC alone selects fallback; reported HVC faults are never cleared by silence.

## Running

Use the project virtual environment with dependencies from `requirements.txt`.

```bash
# Offline summary: no GPIO, CAN, or OLED opened.
.venv/bin/python main.py

# Tests, including virtual-CAN STOP traffic; no physical equipment needed.
.venv/bin/python -m unittest discover -s tests -v

# Bench mode: opens CAN, sends only STOP, receives feedback; no GPIO required.
.venv/bin/python main.py --stop-only

# Physical controls and OLED; requires real Pi hardware and configured CAN.
.venv/bin/python main.py --hardware
```

`--hardware` is not an enable bypass. Startup sends STOP. The rocker must be
observed OFF, then switched ON with fresh fault-free charger feedback and valid
limits before START is sent. Booting with the rocker ON cannot start charging.
After completion or a fault, clear the fault cause and deliberately cycle OFF/ON.
Healthy feedback returning alone cannot restart charging. Panic has no documented
clear message, so it remains inhibited until process restart after inspection.
GPIO/OLED initialization or loop errors request STOP and close the application.

## Fail-safe behavior implemented

- Extended command ID `0x1806E5F4`, feedback ID `0x18FF50E5`, 8-byte frames.
- Big-endian voltage/current fields in 0.1-unit increments; round downward.
- Periodic commands every 1 second, plus immediate changes and STOP requests.
- Feedback timeout at 3 seconds; command scheduling gap at 2 seconds faults.
- Bounded nonblocking receive loops and a 50 ms CAN send timeout.
- All documented charger fault bits inhibit charging. Reserved bits are retained.
- HVC IO summary (SDC/IMD/BMS OK), BMS error/state, panic, and protection-line
  fault messages are decoded from `dbc/hvc.dbc`. Each reported fault remains
  recorded until its own healthy message arrives; controller faults also require
  operator re-arm. SOC loss does not erase a previously reported fault.
- HVC current-limit direction is unconfirmed. Use the smaller of the two reported
  magnitudes conservatively; retain it through loss until a new limit arrives.
- Missing HVC bus is retried every 5 seconds; missing charger transport cannot start.
- CAN errors, invalid targets, operator OFF and orderly shutdown request STOP;
  faults latch. STOP uses control byte `01` **and** zero current.

No automatic enable is inferred from a CAN connection. STOP is best-effort and
is not proof of HV isolation. The TC's reported 5-second command watchdog is an
additional device behavior, not a substitute for the analog shutdown circuit.
No timing/compliance claim is made for hardwired shutdown or process/power loss.

## CAN setup and bench verification

Defaults in `config/settings.py`: **can0 = HVC at 500 kbit/s**, **can1 = charger
at 250 kbit/s**. The interface names are configurable and must be different.
Confirm the exact Waveshare HAT variant, oscillator, interrupt pins and device-tree
overlays; this repository does not install or guess them.

On the Pi, after the HAT is correctly configured:

```bash
sudo apt-get install can-utils
ip -details link show
sudo ip link set can0 up type can bitrate 500000
sudo ip link set can1 up type can bitrate 250000
ip -details -statistics link show can1
candump can1
```

Verify CAN H/L wiring, power/reference/isolation and termination. The charger has
no built-in termination according to the brief; provide the required 120-ohm
termination at each bus end. Confirm interface assignment experimentally.
First observe feedback `18FF50E5` with receive-only `candump`, then use the
STOP-only application in the intended disconnected bench setup. No traffic can
also indicate a missing wake/enable condition rather than a broken CAN interface.

## Remaining hardware/vendor verification

- Model confirmed by owner: **HK-LF-540-14**. Protocol 1000 at 250 kbit/s is
  implemented from the provided brief; confirm the unit is not vendor-customized.
- Feedback current sign location remains ambiguous: raw bytes and `current_raw_u16`
  are retained; `current_amps` is `None` and OLED current is unknown.
- Confirm HVC current-limit direction, SOC period (one-second timeout is provisional),
  and IO/state/protection-line semantics against the running HVC firmware.
- Verify analog SDC actually removes charge permission independently, including
  missing Pi power/process, disconnected CAN and cell/temperature faults.
- Verify model-specific wake/enable wiring, connector pinout, contactors/HVIL,
  AC/thermal derating and rectifier taper/termination behavior.
- Calibrate the RS50 lookup table before relying on its SOC targets.

Implementation reuses existing `controller/charger.py`, `controller/bms.py`,
`hardware/can_bus.py`, `controller/state.py`, `config/settings.py` and `main.py`.
Only one new test file was needed for this TC integration: `tests/test_charger.py`.
The automated suite uses mocked transports and a virtual CAN bus; it does not
verify physical charger operation or certify electrical/rules compliance.
