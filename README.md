# op1-midi

OP-1 Field advanced MIDI functionality — live BPM tracking, per-track volume, pan, and mute via CC messages over USB-C.

## Phase 1 (current)

- MIDI device detection and connection (`src/midi_connection.py`)
- Live BPM calculation from incoming clock ticks (`src/clock.py`)
- CC message sender for volume, pan, and mute on tracks 1–4 (`src/controller.py`)
- CLI test script for milestone verification (`src/test_cli.py`)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run the CLI test

Connect the OP-1 Field via USB-C. Enable MIDI sync output on the device, then press Play.

```bash
python -m src.test_cli
```

The script will:
1. Auto-detect the OP-1 Field by port name (falls back to manual selection)
2. Print live BPM every 2 seconds
3. Toggle mute on track 1 every 4 beats

Stop with **Ctrl+C** — the port is closed cleanly on exit.

## MIDI clock math

The MIDI spec defines **24 PPQN** (Pulses Per Quarter Note). BPM is derived as:

```
BPM = 60 / (24 × average_tick_interval_in_seconds)
```

The last 24 tick intervals are averaged to smooth jitter.

## CC assignments

| CC | Function | Range | Notes |
|----|----------|-------|-------|
| 7  | Volume   | 0–127 | |
| 9  | Mute     | 0-127 | >= 64 = muted |
| 10 | Pan      | 0–127 | 64 = center |

Tracks 1–4 map to MIDI channels 1–4.
