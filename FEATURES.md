# Features

## In progress
- [ ] UI redesign to match OP-1 Field track mix screen aesthetic
- [ ] Pan control as a rotary knob (12 o'clock = center)

## To do
- [ ] Play / Stop buttons in the header: send MIDI Start (0xFA) and Stop (0xFC) transport messages to the OP-1
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
- [x] PyQt6 desktop UI: dark theme, 4 track strips, live BPM display
- [x] Curve automation engine: Linear, Sine, Ease In/Out, Hold — beat-synchronized, loopable
- [x] Automation panel in UI: per-track clip scheduling with active clip list
- [x] App → OP-1 sync: moving a control in the app sends CC to the OP-1 (volume, pan, mute)
- [x] Track color accuracy: matched from OP-1 Field mixer screen — blue, ochre, blue-gray, brick orange-red
