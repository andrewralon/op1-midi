# Features

## To do
- [ ] Show selected LFOs in waveform view: when running, display selected active LFOs in the waveform preview (fall back to all active LFOs if none are selected)
- [ ] LFO curve colors match tracks: color each LFO automation curve to match its assigned track color(s)
- [ ] Automation / fader conflict: manually moving a fader while automation is running should cancel that automation clip
- [ ] Graceful MIDI disconnect: detect OP-1 unplug mid-session, update UI to reflect disconnected state, show reconnect dialog instead of crashing
- [ ] Preset saving: save/load slider positions and automation clips as JSON
- [ ] Startup tempo mode detection: detect whether OP-1 is in Beat Match or MIDI Sync mode at launch and set the UI accordingly (Beat Match auto-detected; MIDI Sync/Free/PO Sync/1/16 indistinguishable via MIDI — startup log added to help test empirically)
- [ ] BPM as LFO target: expose BPM as an automation parameter so LFOs can modulate app (and therefore OP-1 clock) tempo
- [ ] Per-track FX + LFO params: add OP-1 MIDI CC params for per-track FX controls and per-track LFO settings (see OP-1 MIDI spec)
- [ ] Master FX params: add OP-1 MIDI CC params for master FX controls (see OP-1 MIDI spec)
- [ ] Master volume + compression params: add OP-1 MIDI CC params for master volume and master compression (see OP-1 MIDI spec)

## Not possible
- ✗ OP-1 → App sync: the OP-1 Field does not transmit CC messages when its mixer controls are changed, so there is no way to detect volume, pan, or mute state from the device side over MIDI

## Done
- [x] Project scaffold (venv, requirements.txt, .gitignore, src/ layout)
- [x] MIDI device detection and connection (auto-detect OP-1 by port name)
- [x] Clock listener: 24 PPQN tick counting, smoothed BPM calculation, beat callback
- [x] Controller: CC 7 (volume), CC 9 (mute), CC 10 (pan) on channels 1–4
- [x] CLI test script (test_cli.py): live BPM, mute toggle every 4 beats
- [x] PyQt6 desktop UI: dark theme, 4 track strips
- [x] Curve automation engine: Linear, Sine, Ease In/Out, Hold — beat-synchronized, loopable
- [x] Automation panel in UI: per-track clip scheduling with active clip list
- [x] App → OP-1 sync: moving a control in the app sends CC to the OP-1 (volume, pan, mute)
- [x] Track color accuracy: matched from OP-1 Field mixer screen — blue, ochre, blue-gray, brick orange-red
- [x] UI redesign: centered track strips, per-track mute button (colored header, number only), volume fader with red fill below handle, value label, pan knob with L/R labels
- [x] Pan knob: custom-drawn dark circle with line indicator (orange at center, white off-center); 12 o'clock = center (MIDI 64)
- [x] Transport buttons: Play (MIDI Start / Continue), Stop (MIDI Stop) — left column beside tracks
- [x] Tape scrub buttons: ← / → send CC 82 (prev bar) and CC 83 (next bar) with Song Position Pointer for accurate resume position
- [x] MIDI clock generator: app acts as MIDI master, sends 24 PPQN clock continuously; OP-1 set to MIDI Sync mode locks to app tempo
- [x] BPM spinbox: set tempo 20–300 BPM with one decimal place; arrow keys update live, Enter commits typed value
- [x] Octave shift: CC 79 (< 64 = down, ≥ 64 = up) — note: only active on OP-1 in keyboard/synth mode, not tape mode
- [x] LFO panel: waveform preview, rate/depth/center controls, range readout on same row, Start/Stop Selected/Stop All
- [x] LFO Random curve: sample-and-hold waveform — 8 steps per cycle, each holding a deterministic pseudo-random value
- [x] MIDI port list starts at 1: manual port selection prompt numbers ports from 1 instead of 0
- [x] Color palette refactor: variables reorganized into three groups (UI elements, OP-1 track colors, extras) with semantic names (`_BLUE_1`, `_OCHRE_2`, `_GRAY_3`, `_ORANGE_4`, `_FADER`, `_GROOVE`, `_KNOB_RIM`, etc.)
- [x] show_palette.py: dev script that opens a PyQt6 window showing all color swatches and hex values from the current palette
