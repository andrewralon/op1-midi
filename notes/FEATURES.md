# Features

## To do
- [ ] Generic MIDI device support: allow the app to connect to any MIDI device, not just OP-1s. Remove the OP-1 keyword filter from port detection; let the user pick a port from a list. Disable or hide OP-1-specific features (tape scrub, octave shift, BLE detection) when a non-OP-1 device is selected.
- [ ] Desktop executables: package the app as a standalone binary for macOS and Windows using PyInstaller (or similar), so users can run it without a Python environment.
- [ ] GitHub Actions release workflow: on GitHub release publish, automatically build the macOS and Windows executables and upload them as release artifacts. Triggered by the `release: published` event; one job per platform using hosted runners.
- [ ] iOS port: refactor the UI layer to run on iOS (e.g. via Kivy, BeeWare/Toga, or a web-based frontend). Keep the existing PyQt6 desktop path intact so the app can still be launched from Python; the iOS target should share the core engine (`automation.py`, `clock.py`, `controller.py`) and add a separate UI entry point.
- [ ] Automation / fader conflict: manually moving a fader while automation is running should cancel that automation clip
- [ ] Preset saving: save/load slider positions and automation clips as JSON

## Not possible
- ✗ OP-1 → App sync: the OP-1 Field does not transmit CC messages when its mixer controls are changed, so there is no way to detect volume, pan, or mute state from the device side over MIDI
- ✗ Startup tempo mode detection: MIDI only exposes two groups — OP-1 sending clock (Beat Match / PO Sync / 1/16) vs silent (FREE / MIDI Sync). Modes within each group are indistinguishable; jitter overlap rules out finer discrimination. The app now auto-detects the two groups and labels them accordingly. Full empirical results in RESEARCH.md.

## Done
- [x] Project scaffold (venv, requirements.txt, .gitignore, src/ layout)
- [x] MIDI device detection and connection (auto-detect OP-1 by port name)
- [x] Clock listener: 24 PPQN tick counting, smoothed BPM calculation, beat callback
- [x] Controller: CC 7 (volume), CC 9 (mute), CC 10 (pan) on channels 1-4
- [x] CLI test script (test_cli.py): live BPM, mute toggle every 4 beats
- [x] PyQt6 desktop UI: dark theme, 4 track strips
- [x] Curve automation engine: Linear, Sine, Log, Exp, Hold — beat-synchronized, loopable
- [x] Automation panel in UI: per-track clip scheduling with active clip list
- [x] App → OP-1 sync: moving a control in the app sends CC to the OP-1 (volume, pan, mute)
- [x] Track color accuracy: matched from OP-1 Field mixer screen — blue, ochre, blue-gray, brick orange-red
- [x] UI redesign: centered track strips, per-track mute button (colored header, number only), volume fader with red fill below handle, value label, pan knob with L/R labels
- [x] Pan knob: custom-drawn dark circle with line indicator (orange at center, white off-center); 12 o'clock = center (MIDI 64)
- [x] Transport buttons: Play (MIDI Start / Continue), Stop (MIDI Stop) — left column beside tracks
- [x] Tape scrub buttons: ← / → send CC 82 (prev bar) and CC 83 (next bar) with Song Position Pointer for accurate resume position
- [x] MIDI clock generator: app acts as MIDI master, sends 24 PPQN clock continuously; OP-1 set to MIDI Sync mode locks to app tempo
- [x] BPM spinbox: set tempo 20-300 BPM with one decimal place; arrow keys update live, Enter commits typed value
- [x] Octave shift: CC 79 (< 64 = down, ≥ 64 = up) — note: only active on OP-1 in keyboard/synth mode, not tape mode
- [x] LFO panel: waveform preview, rate/depth/center controls, range readout on same row, Start/Stop Selected/Stop All
- [x] Tempo LFO: BPM exposed as LFO target; LFOs modulate app clock tempo with float precision; BPM restores to original value when Tempo LFO is stopped
- [x] Graceful MIDI disconnect: detects OP-1 unplug via port-name polling (500ms), stops clock threads immediately to prevent rtmidi segfault, shows red banner; auto-reconnects when device reappears
- [x] LFO Random curve: sample-and-hold waveform — 8 steps per cycle, each holding a deterministic pseudo-random value
- [x] MIDI port list starts at 1: manual port selection prompt numbers ports from 1 instead of 0
- [x] Color palette refactor: variables reorganized into three groups (UI elements, OP-1 track colors, extras) with semantic names (`_BLUE_1`, `_OCHRE_2`, `_GRAY_3`, `_ORANGE_4`, `_FADER`, `_GROOVE`, `_KNOB_RIM`, etc.)
- [x] show_palette.py: dev script that opens a PyQt6 window showing all color swatches and hex values from the current palette
- [x] LFO curve colors match tracks: waveform preview draws in each selected track's color; multiple non-inverted tracks alternate colors in 16px segments; inverted tracks draw a second mirrored curve in their own colors; Tempo LFO uses accent green
- [x] Active LFO waveform view: selecting rows in the active LFOs list shows each selected LFO as its own curve (correct wave shape, rate, track color); deselects on click-away within app; persists when app goes to background; click selected row again to deselect
- [x] Exp LFO curve: exponential shape — slow start, fast arrival; the exact complement of `log` (which is fast start, slow arrival). Each half-cycle uses `(10^t − 1) / 9` to mirror the `log1p` mapping.
- [x] Sweep LFO curves: `sweep up` and `sweep down` chirp waveforms — oscillation frequency increases (or decreases) linearly across the cycle. 4 complete oscillations per sweep; `sweep up` uses `sin(2π·4·t²)` and `sweep down` uses `sin(2π·4·(2t−t²))` so instantaneous frequency sweeps from 0→max or max→0.
- [x] No-device mode: run the app without a MIDI device — `--no-device` flag, auto-activates when no MIDI ports are found, `[0] no device` option during manual port selection; status bar shows **● no device** in gold; mixed real+no-device connections show both port names
- [x] Bluetooth MIDI: auto-detects BLE-MIDI ports alongside USB (same `op-1` keyword matches both); BLE detected when port name lacks the 'MIDI N' suffix (macOS/CoreMIDI heuristic); status bar appends **(bt)** with tooltip; BPM smoothing doubles (48 ticks) to absorb BLE jitter
- [x] Volume display accuracy: app and OP-1 now show identical values across all 100 steps. OP-1 uses `v * 99 // 127`; app uses ceiling inverse `(v * 127 + 98) // 99` for a perfect round-trip with no off-by-one mismatches.
- [x] Per-track FX + LFO params: CC 54-57 (patch FX 1-4) and CC 58-61 (patch LFO 1-4) exposed as LFO targets in the automation panel; sent on track channels 1-4 matching the volume/pan/mute pattern.
- [x] Master LFO support: **M** button added to the LFO panel (green, same 3-state style as tracks). Selecting a master param (tempo) disables track 1-4 buttons and enables M; M auto-activates to "on" state. Second click inverts the curve, third click turns M off — identical behavior to per-track buttons. `_MASTER_PARAMS` frozenset makes adding future master params (master volume, compression) a one-line change.
- [x] Master FX params: add OP-1 MIDI CC params for master FX controls (see OP-1 MIDI spec)
- [x] Master volume + compression params: add OP-1 MIDI CC params for master volume and master compression (see OP-1 MIDI spec)
- [x] One-shot LFOs: `loop` flag on `LfoClip` (default true). When false, the engine auto-removes the LFO after one full cycle. UI: **1×** button directly below Loop, same style. Active LFOs list: looping clips show no marker; one-shot clips show `[×1]` and disappear automatically when the cycle completes.
- [x] Narrow layout: ~24% width reduction. Track strips 100→75px; pan dial 44→36px; volume digit font 40→26pt; fader 23→16px wide; preview 65→55px; LFO list 96→80px; track buttons 36→30px; transport buttons 44→38px; tighter margins and spacing throughout. Window minimum 700→535px.
