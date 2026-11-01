# Deadman switch and E-stop

A mowing rover needs two separate ways to stop:

- **Deadman.** The driver holds a momentary switch to drive. Releasing it stops the mower.
- **E-stop.** Anyone can stop the mower at any time, and it stays stopped until someone resets it
  on purpose.

The rover's original wiring already stops everything safely: its E-stop ③ opens the 12 V and 24 V
leads, which drops the ⑫ power relays to the track controller and stops the gas engine (and the
blade on its shaft). The deadman and the wireless E-stop are just **two more switches in series with
③ on the same two leads**. ArduPilot sits behind that as a second layer.

![Safety chain wiring](safety-chain.svg)

## Why ArduPilot alone can't be the stop

The track controller runs in **mixed mode**: Cube OUT1 is throttle, OUT2 is steering, and 1500 µs is
neutral on both. In this mode **steering on its own spins the tracks**: with OUT1 at 1500 and OUT2
deflected, the mower turns on the spot. In ArduPilot Rover 4.6.2:

| Mechanism | OUT1 (throttle) | OUT2 (steering) | Stops the tracks? |
|---|---|---|---|
| Motor emergency stop (`RCx_OPTION=31`) | forced to 1500 | **still live**: `SRV_Channel::should_e_stop()` skips GroundSteering | **No** |
| Disarm / `FS_ACTION=5` (Terminate) | 1500 | **still live**: `AP_MotorsUGV::output_regular()` always outputs steering, and Auto keeps steering while disarmed | **No** |
| **Hold mode** | 1500 | **1500**: `ModeHold::update()` | **Yes**, as long as ArduPilot is running and stays in Hold |

ArduPilot also can't act if it crashes, browns out, or loses a signal wire, and it has no control
over the gas engine or the blade. So the primary stop is the hardware chain.

![Which layer stops the mower](stop-coverage.svg)

## Original wiring

Photos are in [`../original_wiring_images/`](../original_wiring_images/). The circled numbers in the
diagrams match the photo file numbers where one exists.

| # | Component | Notes |
|---|---|---|
| ① | Battery string | 4 × 12 V in series = 48 V, with 12 V and 24 V taps |
| ② | Master switch | Blue rotary isolator, battery negative → chassis |
| ④ | Circuit breaker | CHNT DIN-rail breaker on the string (rating to verify) |
| ⑤ | Main Power selector (总电源) | CHNT NP4 2-position, DPST on the 12 V and 24 V lines |
| ③ | Rover E-stop (急停) | Red twist-reset mushroom. Its three poles (GND, 12 V, 24 V) all **open when pressed**. |
| ⑥ | Battery balancer | Keeps the four 12 V batteries balanced |
| ⑫a | Power relay, top | SPST, 24 V coil via ③; switches **48 V** to the track motor controller |
| ⑫b | Power relay, bottom | SPST, 24 V coil via ③; switches **24 V** to the track motor controller |
| ⑬ ⑭ | Track motor controller + motors | Dual channel with encoder A/B ports, mixed mode (ch1 throttle, ch2 steer) |
| ⑮ | RC receiver | 12 V via ③ |
| ⑨ ⑩ | Engine Start / Stop | CHNT NP4 push buttons, 12 V. Don't hold Start more than 2 s. |
| ⑯ | Gas engine controller | Electronic, 12 V via ③. Removing its 12 V stops the engine. |
| ⑰ | Gas engine | Drives ⑱ and ⑲ |
| ⑱ | Mowing blade | Mounted directly on the engine output shaft: it stops only when the engine stops |
| ⑲ | Generator | Driven by the engine, charges the battery string |

## Layer 1: the hardware chain (primary)

③ already opens the 12 V and 24 V leads. ㉓ and ㉔ go **in series with it on both leads**. Nothing
else is added: the existing ⑫ relays and ⑯ engine controller do the stopping.

```
⑤ Main Power ─ ③ rover E-stop ─ ㉓ wireless E-stop ─┬─ ㉔ deadman ─ 24 V → ⑫a/⑫b coils → ⑬ track controller
  (12 V + 24 V)    (3 poles)        (2 poles)          │   (2 poles)  ─ 12 V → ⑯ engine controller → ⑰ engine + ⑱ blade
                                                       └─ 12 V tap: ⑮ receiver + ㉔ module power
```

Every device must be closed for the leads to carry power. Any single device stops the tracks, the
engine and the blade; none of them can start anything on its own.

| # | Device | Contact | Opens when | Resets |
|---|---|---|---|---|
| ③ | Rover E-stop (original) | 3 poles, open when pressed | pressed | twist to release |
| ㉓ | Wireless E-stop receiver | **2-pole** NO relay, held closed by the transmitter's heartbeat | ㉒ pressed, heartbeat lost (dead battery, out of range) | deliberate reset on the handheld or receiver |
| ㉔ | Deadman relay (RC switch module on receiver ch5 PWM) | **2-pole** NO, closed only while ch5 is held | switch released, no PWM pulses, receiver unpowered | pressing the deadman again |

Each of ㉓ and ㉔ needs **two poles** (one DPST relay, or two contacts on the module), one per lead.

### Where the module power comes from

The wires have to land in the right places; otherwise a device can cut its own power:

- **㉓ module:** power it from between ③ and ㉓, upstream of its own contacts.
- **⑮ receiver and the ㉔ module:** power them from the 12 V lead **between ㉓ and ㉔**. If ㉔ cut its
  own receiver's power, releasing the deadman would kill ch5 and it could never close again.
- **⑳ Cube:** power it from the electronics bus (PM02), not through ③, so it keeps running and
  logging through a stop.

This placement also gives ArduPilot E-stop feedback with no extra wiring. When ③ or ㉓ opens, ⑮ loses
power and the SBUS stream stops. ArduPilot's RC failsafe then switches to Hold (Layer 2).

### The engine stops on every stop

The blade sits on the engine shaft, so the only way to stop the blade is to stop the engine. Every
deadman release and every E-stop therefore stops the engine, and it has to be restarted with ⑨ Start
afterwards.

### Rules that make it fail-safe

- **Open to stop.** Every device is normally open and closed only while powered or held. A broken
  wire, a blown fuse or a dead module stops the mower.
- **Rate the ㉓ and ㉔ contacts** for the current on each lead: the ⑫ coils on the 24 V lead, and ⑯
  plus ⑮ on the 12 V lead.
- **The RC switch module must turn its output off on signal loss.** It must not hold its last state.
  Check the datasheet, then test it.
- **Set the receiver's failsafe correctly.** Use "no pulses", or a preset failsafe with ch5 =
  released. **Never use "hold last values":** with that, a dead transmitter battery looks like a held
  deadman. Receivers take about 0.5–1 s to declare failsafe, which is 1–2 m of travel at 2 m/s.
  Re-test after every rebind or receiver firmware update.
- **Use a dedicated wireless E-stop**, not a second hobby radio. Industrial units send a continuous
  heartbeat, open within about 0.5 s when it stops, latch, and run on their own radio and battery.
  A failure in the driving radio therefore can't also disable the E-stop.
- **Plan for slopes.** With power removed, some tracked drives freewheel. If the mower can roll on
  your slopes, add spring-applied brakes that engage with power off, or use the controller's brake
  input.

## Layer 2: ArduPilot (in `config/autopilot_base.yaml`)

| Param | Value | Effect |
|---|---|---|
| `RC5_OPTION` | 54 (Hold) | Deadman released (HIGH) → Hold. Pressed (LOW) → back to the mode-switch mode. |
| `RC5_REVERSED` | 1 | Makes "released" read HIGH. Drop it if your transmitter already sends HIGH when released. |
| `RC_OPTIONS` | 160 | Bit 7 `ALLOW_SWITCH_REV` (needed for `RC5_REVERSED` to apply to a switch) + existing bit 5. Bit 2 (ignore receiver failsafe) stays off. |
| `FS_THR_ENABLE` / `FS_THR_VALUE` | 1 / 910 | RC failsafe on signal loss, or when ch1 is below 910 µs |
| `FS_TIMEOUT` | 1.5 | Seconds without RC before the failsafe acts |
| `FS_ACTION` | 2 (Hold) | RC failsafe → Hold. This is also the E-stop feedback: ③ / ㉓ open → ⑮ unpowered → Hold. **Never 5 (Terminate):** disarm leaves steering live. |
| `INITIAL_MODE` | 4 (Hold) | Boot in Hold. Only lasts until RC appears; see below. |
| `BTN_ENABLE` | 0 | No feedback wiring to the Cube's AUX pins (`SERVO9/10_FUNCTION` back to 0). |

Behaviour in practice:

- **Boot.** The RC5 Hold switch is **not** applied at boot. About 200 ms after RC appears, the mode
  switch (`MODE_CH=8`) picks the mode from `MODE1..6`, which are all Manual in the base.
- **Deadman released.** ㉔ opens (tracks and engine stop) and ch5 sends the Cube to Hold. Pressing
  the deadman returns to the mode-switch mode, Manual. A mission does **not** resume by itself:
  restart Auto from the GCS or skynet. If you ever map a mode-switch position to Auto, pressing the
  deadman in that position resumes the mission.
- **E-stop (③ or ㉓).** The receiver loses power, and after `FS_TIMEOUT` the RC failsafe puts the
  Cube in Hold. It stays armed. After the reset the receiver comes back; press the deadman to return
  to Manual, then restart the engine.

### Gaps in Layer 2 (Layer 1 covers all of them)

1. **Mode changes while released.** Moving the mode switch, or a GCS or skynet mode command, takes
   the mower out of Hold. In mixed mode it could then steer, but ㉔ keeps both leads open.
2. **Steering while stopped in Manual.** The steering stick drives OUT2 even when disarmed. Only the
   open chain keeps the tracks still.
3. **A chain wire breaking below the ⑮ tap.** ⑫ drops and the tracks stop, but the receiver is still
   powered, so ArduPilot doesn't know until the deadman is released.
4. **Cube or wiring failure.** If the Cube crashes, browns out or loses its signal wire to the
   controller, ArduPilot can't act.

A Lua script on the Cube could narrow gaps 1–2. It would read ch5 directly and force OUT1/OUT2 to
1500 whenever ch5 is released, regardless of mode or arming state. It isn't configured yet.

## Procedures

**Power-up:**
1. Make sure every E-stop is released or reset and the deadman is not pressed.
2. Power on with ⑤. The Cube boots in Hold, then follows the mode switch once RC appears.
3. Press and release the deadman once, so ch5 Hold is engaged.
4. Hold the deadman (the chain must be closed for ⑯ to have 12 V) and start the engine with ⑨.
5. Arm deliberately. Hold the deadman to drive.

**After a stop (deadman release or E-stop):**
1. Find out why it was pressed.
2. Centre the sticks.
3. Reset the E-stop if one was pressed.
4. Hold the deadman: the Cube returns to Manual.
5. Restart the engine with ⑨ (no more than 2 s of cranking).

## Bench test (tracks and blade off the ground, before field use)

1. **Radio calibration screen:** ch5 reads **HIGH when released** and LOW when pressed. If not, flip
   `RC5_REVERSED`.
2. **Deadman:** arm in Manual and hold the deadman. Drive, then release mid-turn. ⑫ drops, both
   tracks stop, the engine and blade stop, and the mode shows Hold.
3. **Auto:** start Auto from the GCS with a mission. Release during a pivot turn: everything stops.
   Pressing again returns to **Manual**, not Auto.
4. **Transmitter failure:** hold the deadman, then switch the RC transmitter off. ㉔ opens within
   the receiver's failsafe time. Repeat by pulling the transmitter battery.
5. **Wireless E-stop ㉓:** press it. Everything stops and stays stopped until reset. The Messages tab
   shows the radio failsafe and the mode shows Hold. Reset it: the mode stays Hold until the deadman
   is pressed. Turn the handheld off, or walk out of range: the heartbeat is lost and it stops.
6. **Rover E-stop ③:** same checks as step 5.
7. **Power taps:** with ③ and ㉓ closed, release the deadman and confirm the receiver stays powered
   (ch5 still reads on the radio calibration screen). Press again: ㉔ closes.
8. **Wiring faults:** pull a lead wire after ㉔, and ⑫ drops and the engine stops.
9. **Cube failure:** with the tracks running, pull the Cube's power. Releasing the deadman still
   stops the tracks and the engine.
10. **Power-cycle:** check the power-up procedure above.
