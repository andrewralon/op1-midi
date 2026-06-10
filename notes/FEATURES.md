# Features

## To do
- [ ] Sweep curves: add `sweep up` and `sweep down` LFO waveforms — a chirp/frequency-sweep shape where the oscillation rate accelerates (or decelerates) across the cycle. Naturally one-shot; a sweep-up starts at the minimum rate and reaches the maximum rate by the end of one cycle.
- [ ] One-shot LFOs: add a `loop` flag to `LfoClip` (default true). When false, the engine auto-removes the LFO after one full cycle. UI needs a "start once" or "1-shot" trigger or a 1x toggle alongside Start. Sweep curves should default to one-shot. The active LFOs list would show them disappearing automatically on completion.
- [ ] Master LFO support (tempo, volume, compression, etc.): add an **M** track button (same 3-state style as the 1-4 buttons, colored `_ACCENT` / green) for targeting master/global parameters. Selecting M with a master-capable param (e.g. Tempo) routes the LFO to that master target; clicking M a second time inverts the curve, just like the per-track invert already works. Generalizes to future master params (master volume, master compression) without further UI changes.
- [ ] Automation / fader conflict: manually moving a fader while automation is running should cancel that automation clip
- [ ] Preset saving: save/load slider positions and automation clips as JSON
- [ ] Per-track FX + LFO params: add OP-1 MIDI CC params for per-track FX controls and per-track LFO settings (see OP-1 MIDI spec)
- [ ] Master FX params: add OP-1 MIDI CC params for master FX controls (see OP-1 MIDI spec)
- [ ] Master volume + compression params: add OP-1 MIDI CC params for master volume and master compression (see OP-1 MIDI spec)

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
- [x] Curve automation engine: Linear, Sine, Ease In/Out, Hold — beat-synchronized, loopable
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
- [x] Ease In LFO curve: exponential shape — slow start, fast arrival; the exact complement of `log` (which is fast start, slow arrival). Each half-cycle uses `(10^t − 1) / 9` to mirror the `log1p` mapping.
