# RS50 SOC-to-voltage scaffold

Research date: 2026-11-12. Cell assumed: Reliance INR21700-RS50.

## Sources and limits

The [manufacturer A0 specification, mirrored PDF](https://static.dianchi.cn/uploads/2025/05/13/d9uusrhhapla28skjw.pdf)
specifies 3.6 V nominal, 4.2 V end-of-charge, 2.5 V discharge cutoff,
and at least 4.95 Ah capacity. Standard charging is 2.5 A CC/CV with
100 mA termination at 25 ± 3 °C. The
[readable manufacturer specification](https://manuals.plus/m/25641b0d89a05cc0f8b879f1eb52fcab8ca7032b89a10769bc7a32d40949503f)
provides those conditions. Neither the accessible specification text nor the
[About:Energy RS50 characterization article](https://www.aboutenergy.io/post/reliance-rs50-evtol-battery-pack-design)
provided a numerical SOC/OCV table we could verify. The latter describes
load-dependent voltage polarization; discharge voltage is not resting OCV.

## User-supplied table

Replaced the earlier engineering-assumption table with the chart supplied by the
project owner in this conversation. The user explicitly confirmed the storage endpoints:
30% = 3.46 V and 35% = 3.52 V. No extra 5% knot is
retained: values between rows are linearly interpolated.

The chart's source/test conditions were not supplied. These values are not
claimed to be independently verified RS50 OCV measurements. Temperature, aging,
current and hysteresis are not modeled. The original research above supports
cell limits, not the intermediate points in this user-supplied chart.

| SOC (%) | Cell V | 108S pack V |
| --- | --- | --- |
| 0 | 2.50 | 270.00 |
| 10 | 3.15 | 340.20 |
| 20 | 3.35 | 361.80 |
| 30 | 3.46 | 373.68 |
| 35 | 3.52 | 380.16 |
| 40 | 3.56 | 384.48 |
| 50 | 3.65 | 394.20 |
| 60 | 3.76 | 406.08 |
| 70 | 3.85 | 415.80 |
| 80 | 3.95 | 426.60 |
| 90 | 4.06 | 438.48 |
| 100 | 4.20 | 453.60 |

`controller/battery.py` is the executable table. Conversion uses piecewise
linear interpolation, rejects nonfinite/out-of-range SOC, and multiplies by
series count. Parallel count does not affect voltage. A 0% target is not a
request to discharge; charger command handling and enable logic remain TODO.

## Operation without HVC CAN

HVC availability is detected automatically, with no operator mode setting.
`HVCMonitor.receive(message)` recognizes the extended SOC frame defined in
`dbc/hvc.dbc`, validates its payload, and timestamps it with a monotonic clock.
At startup, or once SOC is one second old, `snapshot()` returns unavailable SOC
and `charging_target()` falls back to the estimated voltage target. Fresh valid
SOC automatically restores HVC-assisted operation. Unrelated CAN traffic does
not refresh SOC. The one-second timeout is an integration default that must be
checked against the actual HVC transmission period.

With fresh HVC SOC, the requested voltage is the RS50 maximum pack voltage
(4.20 V × series count: 453.60 V for 108S). At reported SOC greater than or equal
to the operator target, the policy requests STOP and zero current. Using >=
handles telemetry skipping over the exact target. `ChargeSession` latches this
stop until an explicit new charging session; losing SOC cannot restart it.

Without fresh HVC SOC, the voltage is the user-supplied lookup target (426.60 V
at 80% for 108S), with the requested current limit. The rectifier is expected to
handle CV taper and termination, as specified by the project owner. This behavior
has not been verified on hardware. Fallback cannot assert SOC completion.
The OLED's `hvc_available` field is runtime state from the same control snapshot,
not configuration. Missing readings use `None`. Individual cell and temperature
signals still require their own decoding/freshness handling when integrated.
Fallback must not clear a latched fault or grant charge permission by itself.

The hardware loop now sends TC HK-L commands and monitors feedback/faults;
see the README for bench and hardware modes. The rectifier owns CC/CV taper and
termination in fallback. Independent analog SDC is external to the Pi, per the
project owner's system description. No software claim of verified isolation is
made. For fallback lookup values below the HK-LF-540-14's 350 V minimum, the controller
commands 350 V and separately monitors fresh charger voltage against the original
lookup value. At or above that threshold it latches STOP and zero current; if
already above it, no START is sent. Only an explicit new operator session resets
completion. Missing or stale charger feedback inhibits charging. Normal fallback
values at/above 350 V continue to use rectifier taper/termination.
This low-target mode has no CV taper at the lookup voltage; CAN/reporting latency
can cause overshoot. Verify stopped-output voltage sensing and operation below
350 V actual battery voltage with the charger vendor/bench. This does not prove
SOC accuracy or extend the charger's specified hardware operating range. Reaching a voltage target does not prove
that the selected SOC has been reached. Pack voltage cannot detect an individual
overcharged cell; independent cell/temperature protection remains necessary when
HVC telemetry is absent.

For calibration, measure RS50 rested OCV at known coulomb-counted SOC steps under
controlled temperature, retain test conditions and raw data, and replace the
user-supplied knots. Validate the resulting CV targets and termination strategy at
the intended pack charging currents. Do not use the datasheet's AC impedance as
a DC charging-voltage correction.
