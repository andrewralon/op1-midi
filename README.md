# op1-lfo-hero

Custom MIDI LFOs (low frequency oscillators) for the Teenage Engineering OP-1 Field synthesizer. Controls per-track volume, pan, mute, FX, LFO parameters, and master FX/compressor parameters with beat-synchronized automation curves. Handles these OP-1 tempo modes:
1. `BEAT MATCH` aka `op1` (ext clock) -> op1 sends clock to app: used to sync the LFOs
2. `MIDI SYNC` aka `app` (int clock) -> app sends clock to op1: generates tempo, transport, and tape navigation commands

![screenshot-1](images/ss-1.png)

---

## Running the App

**Requirements:**
- Teenage Engineering OP-1 Field
- USB-C cable or Bluetooth
- Python 3.11 or newer
- macOS (tested) or Windows/Linux (untested but should work)

With the OP-1 connected and the virtual environment activated:

```bash
source venv/bin/activate
python -m src.app
```

The app auto-detects the OP-1 by port name (looks for "op-1" case-insensitively). If exactly one OP-1 port is found it is selected automatically. If multiple OP-1 ports are detected (e.g. USB and Bluetooth both connected) you will be prompted to choose from the full port list.

### Bluetooth MIDI

Bluetooth LE MIDI is supported alongside USB. When the connected port name contains "Bluetooth" the status bar appends **(bt)** with a tooltip noting the ~15ms additional latency. BPM smoothing doubles automatically to absorb BLE jitter. Note that Tempo LFO requires the app to be clock master and is unavailable over Bluetooth.

### Command-line flags

| Flag | Description |
|------|-------------|
| `--debug` | Enable verbose debug logging to the terminal |
| `--no-device` | Run without a MIDI device — all controls are live but no MIDI is sent |

No-device mode also activates automatically if no MIDI input or output ports are found at startup, or if `no device` is selected during manual port selection. The status bar will show **● no device**.

---

## Using the App

### Transport Controls (left column)

| Button | Action |
|--------|--------|
| **Play** | Sends MIDI Start (first press) or Continue (subsequent presses). OP-1 tape begins playing from the current position. |
| **Stop** | Sends MIDI Stop. OP-1 tape halts. |
| **←** | Sends CC 82 (tape previous bar) and updates the song position pointer. |
| **→** | Sends CC 83 (tape next bar) and updates the song position pointer. |

**Note:** The OP-1 must be in `Midi Sync` mode for Play/Stop/←/→ to affect the tape. In other modes these buttons have no effect on tape transport.

---

### BPM

- Displays the current tempo with one decimal place (e.g. `120.0`)
- The app generates a continuous **24 PPQN MIDI clock** signal — the OP-1 locks to this tempo in MIDI Sync mode
- **Arrow keys** — increment/decrement by 1.0 BPM
- **Type a value** and press **Enter** to set an exact tempo
- Range: 20.0 - 300.0 BPM

Changes take effect immediately; the OP-1's BPM display updates in real time.

---

### Track Strips

Each of the four tracks corresponds to an OP-1 Field mixer channel (tracks 1-4 = MIDI channels 1-4).

#### Mute button (top)
- Colored header button showing the track number
- Click to toggle mute on/off; the button dims when muted
- Sends CC 9 (127 = muted, 0 = unmuted)

#### Pan knob
- Dark circular dial below the fader
- Center position (12 o'clock) = center pan (MIDI 64) — line is **orange**
- Off-center — line is **white**, pointing toward the pan direction
- Click and drag up/down to adjust; sends CC 10
- Labels: **L** (left) and **R** (right)

#### Volume fader
- Vertical slider, range 0-99 (maps to MIDI 0-127)
- Default: **90**
- The filled portion below the handle turns red to show the current level
- The numeric value is shown below the fader
- Drag or click to adjust; sends CC 7

---

### LFO Panel

The LFO panel (below the track strips) applies beat-synchronized automation curves to any track parameter.

#### Waveform selector
Choose the LFO shape:

| Wave | Description |
|------|-------------|
| **Sine** | Smooth S-curve oscillation |
| **Triangle** | Linear ramp up and down |
| **Saw** | Linear ramp up, instant reset |
| **Square** | Instant snap between high and low |
| **Log** | Fast start, slow arrival each half-cycle |
| **Exp** | Slow start, fast arrival each half-cycle (complement of Log) |
| **Sweep Up** | Chirp — oscillation frequency increases linearly across the cycle (4 sweeps total) |
| **Sweep Down** | Chirp — oscillation frequency decreases linearly across the cycle |
| **Random** | Sample-and-hold — 8 deterministic steps per cycle, each holding a pseudo-random value |

#### Waveform preview
A live preview of the selected waveform is drawn in the panel. The number of visible cycles scales with the Rate setting.

When LFOs are running, selecting rows in the **active LFO list** replaces the preview with each selected LFO's actual waveform drawn in its track color. Deselects when you click elsewhere in the app.

#### Track and Master buttons

Each LFO targets one or more tracks. The numbered buttons (1–4) select per-track targets; the green **M** button targets master parameters.

- Click once to activate (normal phase)
- Click again to invert (flipped phase, marked `[inv]` in the active list)
- Click a third time to deactivate

For **Tempo** and other master-only parameters, the track 1–4 buttons are disabled and M activates automatically. For per-track parameters (volume, pan, mute, FX, LFO), M is disabled.

#### Parameter selector

| Parameter | Target | CC |
|-----------|--------|----|
| volume | Per-track channel volume | CC 7 (ch 1-4) |
| pan | Per-track pan | CC 10 (ch 1-4) |
| mute | Per-track mute toggle | CC 9 (ch 1-4) |
| tempo | App clock BPM (modulates LFO engine tempo) | — |
| fx 1–4 | Per-track patch FX parameters | CC 54-57 (ch 1-4) |
| lfo 1–4 | Per-track patch LFO parameters | CC 58-61 (ch 1-4) |

**Tempo LFO:** modulates the app's BPM directly with float precision. The OP-1 display tracks in real time. When the Tempo LFO is stopped the BPM restores to its original value. Requires app-clock mode (MIDI Sync on the OP-1); unavailable when the OP-1 is the clock master or when connected via Bluetooth.

#### Controls (per row)

| Control | Description |
|---------|-------------|
| **Rate** | How many LFO cycles per bar (beat-synced) |
| **Depth** | How much the parameter value swings from center |
| **Center** | The midpoint value the LFO oscillates around |
| **Range** | Readout showing the min-max value the LFO will reach, derived from Center ± Depth |

#### Inverted LFOs

When two or more tracks are selected, the **Invert 2nd+** checkbox becomes available. With it checked, the first selected track gets the normal waveform and every additional track gets the same waveform flipped upside-down — its output is `center - (wave x depth)` instead of `center + (wave x depth)`.

This means when the primary track's value rises, the secondary tracks' values fall by the same amount, and vice versa. Some uses:

- **Stereo pan spread** — assign the same LFO to tracks 1 and 2 with Pan selected and Invert enabled. Track 1 sweeps left while track 2 sweeps right, keeping an even stereo image.
- **Pumping sidechain feel** — automate Volume on two tracks so one ducks while the other swells.
- **Call and response** — run an inverted LFO on a second melody track so phrases naturally dovetail rather than stack.

The active LFO list marks inverted clips with `[inv]` so you can tell them apart at a glance. The waveform preview draws each track's curve in its own color.

#### Buttons

| Button | Action |
|--------|--------|
| **Start** | Begin LFO automation on the selected tracks and parameter |
| **Stop Selected** | Stop automation on the currently selected clip |
| **Stop All** | Stop all running automation clips immediately |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/andrewralon/op1-lfo-hero.git
cd op1-lfo-hero
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
```

### 3. Activate the virtual environment

**macOS / Linux:**
```bash
source venv/bin/activate
```

**Windows:**
```cmd
venv\Scripts\activate
```

You should see `(venv)` in your terminal prompt.

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `mido` — MIDI I/O library
- `python-rtmidi` — low-latency MIDI backend for mido
- `PyQt6` — desktop UI framework
- `numpy` — used by the automation engine

---

## Troubleshooting

**App shows "MIDI Connection Failed"**
- Make sure the OP-1 is powered on and connected via USB-C (or paired via Bluetooth) before launching
- Try a different USB-C cable (some are charge-only)
- On macOS, check **System Settings → Privacy & Security** if any MIDI access prompt was dismissed

**Controls send but OP-1 doesn't respond (volume, pan, mute, transport all ignored)**
- macOS CoreMIDI can get into a bad state where the port appears available but no data flows
- Fix: `sudo pkill -9 coremidi` in the terminal, then unplug and replug the OP-1 — no restart needed

**OP-1 tape doesn't respond to Play/Stop**
- Confirm the OP-1 is in MIDI Sync mode (COM → MIDI → SYNC: MIDI)
- The OP-1 BPM display should show `--` when waiting for clock — if it shows an internal BPM, Sync mode is not active

**BPM on the OP-1 doesn't match the app**
- The OP-1 needs a few seconds of continuous clock signal to lock in; the display may lag slightly after a BPM change

**Left/right buttons stop playback**
- This is a known OP-1 behavior: receiving a Song Position Pointer message while playing causes the OP-1 to stop and wait for a Continue or Start. Press Play after navigating to resume.

**Pan knob jumps unexpectedly**
- QDial uses click-to-set by default. Click and drag vertically for fine control.

---

## MIDI Reference

**Per-track (channels 1-4)**

| CC | Function | Range | Notes |
|----|----------|-------|-------|
| 7  | Volume   | 0-127 | Per channel (track 1-4 = channel 1-4) |
| 9  | Mute     | 0-127 | ≥ 64 = muted |
| 10 | Pan      | 0-127 | 64 = center |
| 54-57 | Patch FX params 1-4 | 0-127 | Per track |
| 58-61 | Patch LFO params 1-4 | 0-127 | Per track |

**Global (channel 1)**

| CC | Function | Range | Notes |
|----|----------|-------|-------|
| 70-73 | Master FX params 1-4 | 0-127 | |
| 74-77 | Master compressor params 1-4 | 0-127 | |
| 79 | Octave   | 0-127 | < 64 = down, ≥ 64 = up (keyboard/synth mode only) |
| 82 | Tape prev bar | 127 | Tape navigation |
| 83 | Tape next bar | 127 | Tape navigation |

**Transport messages**

| Message | MIDI Status | Description |
|---------|-------------|-------------|
| Clock   | 0xF8 | Sent at 24 PPQN continuously |
| Start   | 0xFA | Begin playback from position 0 |
| Continue| 0xFB | Resume from current song position |
| Stop    | 0xFC | Halt playback |
| Song Position Pointer | 0xF2 | Sets resume position in MIDI beats |

OP-1 Field Midi Reference: https://teenage.engineering/guides/op-1#midi-reference
