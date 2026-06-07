# Features

## To do
- [ ] Automation / fader conflict: manually moving a fader while automation is running should cancel that automation clip
- [ ] Graceful MIDI disconnect: detect OP-1 unplug mid-session, show reconnect dialog instead of crashing
- [ ] Preset saving: save/load slider positions and automation clips as JSON

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
