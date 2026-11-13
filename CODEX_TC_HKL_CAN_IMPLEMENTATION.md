# Codex Implementation Brief — TC HK-L Charger CAN Interface (TREV5)

## Objective

Implement a maintainable, testable Python interface to the **TC HK-L series 6.6 kW charger** for the existing TREV5 Raspberry Pi project, using **python-can / Linux SocketCAN** and a Waveshare dual-channel MCP2515 CAN HAT. The charger and BMS will use separate CAN interfaces (tentatively `can0` for charger, `can1` for BMS; make both configurable).

**Read this document before editing code.** Treat it as implementation requirements, not as permission to energize a charger. First deliver a transport/protocol implementation, tests, and a **receive-only or STOP-only bench demonstration**. Do not automatically enable charging when the application starts.

## Project Context / Existing Code

The existing `main.py` is approximately:

```python
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
```

Inspect the *actual repository* before making changes; do not assume its structure beyond the context above. Reuse existing settings, logging, state-machine and testing conventions. Do not replace the current state machine with an independent script or duplicate state transitions.

Suggested additions (adapt to repo):

```text
controller/charger_can.py       # pure codec plus SocketCAN transport/controller
controller/bms_can.py           # only if an existing implementation needs integration; do NOT invent BMS protocol
config/settings.py             # additional CAN settings
 tests/test_charger_can.py      # encoding/decoding and controller behavior
```

## Authoritative Source and Scope

Source: user-provided **“TC Charger 6.6kW 4th gen(1).pdf”**, pages **9–10** for CAN protocol, pages **2–3** for output ranges/bitrate and CAN hardware properties. This is the *standard CAN protocol*, which the datasheet explicitly says can be customized by the vendor. Before connecting to live hardware, confirm the charger's configured protocol/baud rate on the label or with the supplier.

This document distinguishes **stated facts** from **items requiring verification**. Do **not** silently turn uncertain details into asserted protocol behavior.

### Confirmed CAN settings from PDF

- Standard protocol number: **1000**.
- Bit rate: **250,000 bit/s** (the general specs mention 125/250/500 kbps support; the protocol table specifies 250 kbps).
- CAN IDs are **29-bit extended identifiers** (both listed IDs exceed the 11-bit range).
- Command from **BMS/controller → charger**: extended ID **`0x1806E5F4`**, 8-byte data frame, **1000 ms** cycle.
- Feedback from **charger → controller**: extended ID **`0x18FF50E5`**, 8-byte data frame, **1000 ms** cycle.
- Charger stops output and reports communication error after **5 seconds without a control message**. Do not treat this as a functional-safety guarantee or substitute for hardwired shutdown.
- **No built-in CAN terminal resistance** per PDF page 3: provide 120-ohm termination at both physical bus ends as appropriate. Use the correct CAN H/L wiring, transceiver voltage/isolation, and common-reference arrangements specified by hardware manufacturers; validate on the bench.

### Command frame — ID `0x1806E5F4`

| Zero-based byte index | PDF's name | Encoding |
|---|---|---|
| 0 | Voltage high byte | Requested max charge terminal voltage, unsigned 16-bit, **big-endian**, **0.1 V/LSB** |
| 1 | Voltage low byte | same field |
| 2 | Current high byte | Requested max charge current, unsigned 16-bit, **big-endian**, **0.1 A/LSB** |
| 3 | Current low byte | same field |
| 4 | Control | **`0x00` start charging**; **`0x01` stop charging / battery protection** |
| 5–7 | Reserved | Send zero |

Example of **encoding only** (not a recommendation to energize equipment): **400.0 V** → 4000 → `0F A0`; **2.0 A** → 20 → `00 14`; STOP command → `01`. Full STOP payload:

```text
CAN ID: 0x1806E5F4 (extended, DLC=8)
DATA:   0F A0 00 14 01 00 00 00
```

Start/control byte would be `00` instead of `01`, but startup transmission must be independently gated by the application's real hardware safety checks.

Use integer arithmetic/explicit rounding to 0.1-unit increments. Use `struct.pack('>HHBBBB', voltage_decivolts, current_deciamps, control, 0, 0, 0)` or equivalent. Check that the payload is **exactly 8 bytes**.

### Charger feedback frame — ID `0x18FF50E5`

| Zero-based byte index | Meaning | Encoding |
|---|---|---|
| 0–1 | Reported charger output voltage | 16-bit big-endian, 0.1 V/LSB |
| 2–3 | Reported charger output current | 0.1 A/LSB; **direction/sign-bit notation is ambiguous** (see below) |
| 4 | Status bitfield | detailed below |
| 5–7 | Reserved | ignore |

Status byte bits (a bit set to `1` indicates the listed fault):

| Bit | Meaning |
|---|---|
| 0 | Hardware failure |
| 1 | Charger overtemperature protection |
| 2 | AC input voltage problem; charger stops |
| 3 | Battery absent or reverse-connected |
| 4 | CAN receive timeout / communication fault |
| 5–7 | Unspecified / reserved |

**Ambiguous feedback current:** The PDF says *“The highest BIT indicates the symbol, 0: charging 1: discharging”*, adjacent to the feedback current field. It does not unambiguously specify whether this sign bit is the top bit of the 16-bit current word, the top bit of the low byte, or another convention. **Do not assert a signed current measurement yet.** Preserve both `current_raw_u16` and `current_bytes`, and expose `current_amps=None` or an explicitly labelled *unverified* interpretation until field testing or vendor documentation confirms it. For voltage, decode normally.

**Status semantics:** Define named flags. Treat any **documented** fault bit 0–4 as a reason to inhibit charging. Preserve unknown bits in raw status for diagnostics. Document that the frame is broadcast each second.

## Charger/Pack Limits and Safety

The pack described in project discussions is **108s3p**, with a stated **14 A maximum charging current** (this is *not* an instruction to charge at 14 A). Assuming a 4.2 V/cell ceiling, the pack would reach **453.6 V**. The datasheet lists these model-specific DC output ranges:

- **HK-LF-312-20**: **250–450 V**, max 20 A.
- **HK-LF-540-14**: **350–680 V**, max 14 A.

**Important:** A 453.6 V maximum pack voltage is above the 312-model's specified 450 V maximum. Never try to solve this by software commanding beyond hardware ratings. The actual charger model, nominal/full-charge chemistry, BMS voltage/current charge limits, AC input derating, thermal derating and system-level permissions must be confirmed before making operational setpoints.

Define configurable, explicit **hardware limits** and separate **BMS-permitted limits**, using the more restrictive values. Reject commands that exceed approved configuration; do not quietly clamp unsafe requests without providing a visible error. Avoid hardcoding 400 V, 14 A, or full-pack voltage as operational defaults. For initial testing, transmit only STOP frames, with safe configured values, on a disconnected/mock CAN environment.

### Required interlocks before any START command

Only send `control=0` if **all** of the following have been explicitly implemented, evaluated and are healthy:

1. A real, fresh BMS status permits charging; requested setpoints are within its current limits. **Do not fake this with a hardcoded `True` or infer the BMS protocol from the charger datasheet.**
2. Independent emergency stop / shutdown circuit, contactor state, HVIL, and any other Formula SAE electrical safety requirements are satisfied. Integrate with actual inputs and system design; do not assume the charger CAN watchdog meets shutdown requirements.
3. Charger communication is healthy, using configured feedback freshness checks; relevant fault bits are clear.
4. Active operator enable/arming and valid configured charger hardware limits exist.
5. Controller state machine explicitly allows charging.

If these inputs are not currently implemented, **implement the CAN codec and STOP-only transport**, with a blocked `start()` method that raises a clear `SafetyInterlockError` or equivalent. Do **not** implement a command-line `--enable` bypass in production code.

**On any detected fault, BMS permission loss, stale feedback, CAN transport exception, lost safety interlock, or orderly shutdown:** request STOP immediately where possible, latch or transition to fault/disabled in the state machine, and prevent automatic restart without deliberate re-arming. A CAN STOP transmission is *best-effort*, not proof of HV isolation. Do not rely on Python process cleanup for shutdown: hardwired/independent protections are necessary. Discuss communication timeout vs. requirement for low voltage within 5 seconds separately; don't claim this software meets that requirement.

## Implementation Tasks

### A. Codec and data model — pure Python, no hardware dependencies

Implement and unit-test:

- `encode_command(voltage_v: float, current_a: float, stop: bool = True) -> bytes` returning exactly eight bytes, big-endian fields and reserved zero bytes. Validate finite numeric inputs (no NaN/infinities), 0.1-unit representability/rounding, unsigned field range, and **configured hardware/BMS limits at the controller boundary**. The codec itself may be protocol-range-only, but the controller cannot bypass the operational constraints.
- `decode_feedback(data: bytes) -> ChargerFeedback` (dataclass preferred) with raw bytes, decoded voltage, raw current, status flags, and fault names. Reject payload lengths other than 8. Do not fabricate a verified signed amperage value.
- `is_charger_feedback(msg)` checks correct arbitration ID, `is_extended_id=True`, non-RTR/non-error frame, expected DLC 8 before decoding.
- Constants for message IDs, cadence, bit rate and fault masks.

### B. SocketCAN adapter

Create a `ChargerCAN` class accepting a configurable interface name and an injectable `can.BusABC` or thin transport abstraction for tests. Use `can.Message(..., is_extended_id=True, data=...)`. Never assume `can0` always refers to the charger.

API suggestion (adapt naming to existing repository):

```python
class ChargerCAN:
    def send_stop(self, voltage_v: float, current_a: float) -> None: ...
    def send_command(self, voltage_v: float, current_a: float, *, permission: object) -> None: ...
    def poll_feedback(self, timeout_s: float = 0.0) -> ChargerFeedback | None: ...
    def close(self) -> None: ...
```

Do **not** use a trivially forged boolean `permission=True` for production start. Prefer routing start through `ChargerStateMachine` after validating real BMS and hardware permissions. Keep lifecycle ownership clear: only one component creates/closes the socket CAN bus; do not have separate consumers competing to `recv()` from the same bus.

Use `time.monotonic()` for periodic timing and freshness. Ensure the one-second command cadence is not blocked by feedback reception; if main loop runs slowly, use a scheduler/appropriate worker with deterministic shutdown and thread safety, or nonblocking bounded polls. Message missed sends and `can.CanError` must be observable and handled as faults. Commands must not silently continue indefinitely with stale BMS data.

### C. Integrate into state machine

Inspect `controller/state.py` and `config/settings.py` and integrate without breaking their public interfaces. Keep **STOP** as the default / startup mode; no auto-start or energization on boot.

Use explicit states or transitions to express initialization, waiting for permission, active charging, stopping and latched fault (reuse existing state model if available). On transition to stop/fault, attempt to send STOP promptly; don't make a blocking receive postpone stop requests. Require explicit re-arm following faults.

Prefer structured `logging` to `print`, except preserve the app's introductory banner if desired. Include timestamps and CAN ID, raw payload, and parsed status in debug logs. Limit noisy normal logs.

### D. Hardware setup documentation

Document **without claiming verification**:

```bash
python3 -m pip install python-can
sudo apt-get install can-utils
ip -details link show
# Only after correct MCP2515 overlays and HAT wiring are configured:
sudo ip link set can0 up type can bitrate 250000
candump can0
```

Waveshare HAT setup requires the correct device-tree overlays and oscillator/interrupt settings for the exact board model; don't invent those settings. CAN HAT SPI setup, transceiver power, termination and interface numbering must be established experimentally. A useful receive-only test is to listen for extended ID `0x18FF50E5`; do not infer a broken bus merely from no traffic if the charger needs a wake/enable condition.

Also document how to inspect errors and link status (`ip -details -statistics link show can0`) and distinguish the two CAN channels.

### E. Tests (must work with no physical hardware)

Use `pytest` (or the repo's existing framework) and `python-can`'s virtual bus or mocked transport. Cover:

1. Encode 400.0 V, 2.0 A, **STOP** → `0F A0 00 14 01 00 00 00`.
2. Encode same limits with **START control byte** → `0F A0 00 14 00 00 00 00` **in codec unit tests only**. An active controller must still reject START absent live permissions.
3. Reject invalid numeric values, 16-bit overflow, NaN/inf, and bytestring lengths other than 8.
4. Decode a sample feedback voltage and raw current bytes; verify fault flag extraction individually and in combination.
5. Ignore/reject wrong CAN IDs, standard 11-bit frames, RTR and error frames.
6. Confirm command frames use `is_extended_id=True`, DLC=8, and correct ID.
7. Verify STOP on fault, stale BMS data, stale charger feedback, shutdown and CAN send errors.
8. Verify no START on program initialization, no auto-restart after faults, and no bypass of missing safety inputs.
9. Verify periodic scheduling, including high latency/missed frame behavior using a fake monotonic clock if practical.
10. Verify application still starts safely when CAN hardware is missing (logs an unavailable transport/fault instead of enabling charging).

## Deliverables / Definition of Done

- [ ] Added focused charger CAN protocol module with type annotations, docstrings and clear constants.
- [ ] Correct binary command encoding and conservative feedback decoding.
- [ ] Safe state-machine integration, default STOP and no automatic start.
- [ ] Runtime checks for feedback/BMS freshness, defined charger fault flags and CAN errors.
- [ ] Configurable CAN interfaces, charger model limits and desired command cadence.
- [ ] Unit tests for exact payloads, faults, timeouts and safety gating.
- [ ] README section for SocketCAN setup, termination and bench validation.
- [ ] Explicit list of remaining **hardware/vendor verification items** before live charge enable.

## Items to Resolve Rather Than Guess

- Exact charger model and vendor-customized protocol, if any.
- Precise current feedback sign-bit location/semantics (preserve raw current until validated).
- Whether any separately required 12 V wake input, CP/CC signaling, HVIL, AC-side or charger enable hardware is needed for this particular installation. The CAN command alone might not wake or enable the device.
- Exact pinout of the 20-pin signal connector, verified against the correct variant; the uploaded pages reference another table/diagram but do not show a complete unambiguous signal connector pin map in readable form.
- Exact BMS CAN protocol, permission semantics and fault interpretation (not supplied by this charger datasheet).
- Electrical safety and FSAE rule compliance, independent shutdown hardware, and verified discharge response. No simulation/test should claim compliance with safety timing.

## How Codex Should Work

1. Inspect repository files and current tests before editing.
2. Implement the pure encoding/decoding module and tests first.
3. Add the SocketCAN transport behind an injectable interface.
4. Integrate STOP-only behavior into the existing state machine, with safety-gated START as a **future integration point** rather than a functional bypass.
5. Run tests, lint/type checks if configured, and report exactly what passed or failed.
6. In the final summary list changed files, test results, hardware-only validations still needed, and **any unresolved datasheet ambiguities**. Never claim to have tested real CAN traffic if only mocked/virtual CAN was used.
