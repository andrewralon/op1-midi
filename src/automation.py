"""
Beat-synchronized CC automation engine.

Curve math:
  t = clip position normalized to 0.0–1.0.
  Each CurveShape maps t → 0–1, which is then lerped between start/end values.

  LINEAR   — constant rate of change
  SINE     — smooth S-curve: slow at both ends, fastest at midpoint
  EASE_IN  — accelerates from the start (quadratic)
  EASE_OUT — decelerates toward the end (quadratic)
  HOLD     — stays at start_value, snaps to end_value at the last tick

AutomationEngine.on_tick() is wired as ClockListener's tick_callback, so it
runs on the clock daemon thread at ~29 Hz (24 PPQN × BPM / 60).  All public
methods acquire a lock and are safe to call from the Qt main thread.
"""

import math
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

from src.clock import PPQN
from src.controller import Controller


class CurveShape(Enum):
    LINEAR   = auto()
    SINE     = auto()
    EASE_IN  = auto()
    EASE_OUT = auto()
    HOLD     = auto()


class Parameter(Enum):
    VOLUME = "volume"
    PAN    = "pan"
    MUTE   = "mute"


# Displayed names for the UI combo box, in order
CURVE_LABELS: dict[str, CurveShape] = {
    "Linear":   CurveShape.LINEAR,
    "Sine":     CurveShape.SINE,
    "Ease In":  CurveShape.EASE_IN,
    "Ease Out": CurveShape.EASE_OUT,
    "Hold":     CurveShape.HOLD,
}

PARAMETER_LABELS: dict[str, Parameter] = {
    "Volume": Parameter.VOLUME,
    "Pan":    Parameter.PAN,
    "Mute":   Parameter.MUTE,
}


def _apply_curve(t: float, shape: CurveShape) -> float:
    """Map t ∈ [0, 1] through a curve shape, returning a value in [0, 1]."""
    t = max(0.0, min(1.0, t))
    if shape is CurveShape.LINEAR:
        return t
    if shape is CurveShape.SINE:
        # Classic cosine ease: slow→fast→slow
        return (1.0 - math.cos(math.pi * t)) / 2.0
    if shape is CurveShape.EASE_IN:
        return t * t
    if shape is CurveShape.EASE_OUT:
        return 1.0 - (1.0 - t) ** 2
    if shape is CurveShape.HOLD:
        return 0.0 if t < 1.0 else 1.0
    return t


@dataclass
class Clip:
    track: int             # 1–4
    parameter: Parameter
    start_beat: int        # absolute beat number (from ClockListener.beat_count)
    duration_beats: int    # length in beats
    start_value: int       # CC value at t=0  (0–127)
    end_value: int         # CC value at t=1  (0–127)
    curve: CurveShape = CurveShape.LINEAR
    loop: bool = False     # if True, restarts after duration_beats

    def value_at(self, t: float) -> int:
        curved = _apply_curve(t, self.curve)
        return round(self.start_value + (self.end_value - self.start_value) * curved)


class LfoWave(Enum):
    SINE     = "Sine"
    TRIANGLE = "Triangle"
    SAW_UP   = "Saw Up"
    SAW_DOWN = "Saw Down"
    SQUARE   = "Square"
    LOG      = "Log"


LFO_WAVE_LABELS: dict[str, LfoWave] = {w.value: w for w in LfoWave}


def lfo_wave_value(phase: float, wave: LfoWave) -> float:
    """Return oscillation in [-1.0, 1.0] for phase in [0.0, 1.0]."""
    phase = phase % 1.0
    if wave is LfoWave.SINE:
        return math.sin(2.0 * math.pi * phase)
    if wave is LfoWave.TRIANGLE:
        if phase < 0.25:
            return 4.0 * phase
        if phase < 0.75:
            return 2.0 - 4.0 * phase
        return 4.0 * phase - 4.0
    if wave is LfoWave.SAW_UP:
        return 2.0 * phase - 1.0
    if wave is LfoWave.SAW_DOWN:
        return 1.0 - 2.0 * phase
    if wave is LfoWave.SQUARE:
        return 1.0 if phase < 0.5 else -1.0
    if wave is LfoWave.LOG:
        if phase < 0.5:
            t = phase * 2.0
            return 2.0 * math.log1p(t * 9.0) / math.log(10.0) - 1.0
        t = (phase - 0.5) * 2.0
        return 1.0 - 2.0 * math.log1p(t * 9.0) / math.log(10.0)
    return 0.0


@dataclass
class LfoClip:
    """Continuously oscillating automation — always loops."""
    track: int          # 1–4
    parameter: Parameter
    wave: LfoWave
    rate_beats: int     # beats per full cycle
    depth: int          # oscillation half-amplitude in MIDI units
    center_value: int   # MIDI center (0–127)

    def value_at(self, phase: float) -> int:
        """phase: 0.0–1.0 position within one cycle."""
        y = lfo_wave_value(phase, self.wave)
        return max(0, min(127, round(self.center_value + y * self.depth)))


# Fired from the clock thread; used to update UI sliders
AutomationUpdateCallback = Callable[[int, Parameter, int], None]


class AutomationEngine:
    """
    Evaluates active Clips on every MIDI clock tick and sends CC messages.

    Designed for the clock daemon thread via on_tick().  All other methods
    are safe to call from the Qt main thread (they acquire _lock).
    """

    def __init__(
        self,
        controller: Controller,
        update_callback: AutomationUpdateCallback | None = None,
    ) -> None:
        self._ctrl = controller
        self._update_cb = update_callback
        self._lock = threading.Lock()
        self._clips: list[Clip] = []

        # id(clip) → tick_count at which that clip's playback began
        self._active_starts: dict[int, int] = {}
        # id(clip) → last CC value sent, so we skip redundant sends
        self._last_sent: dict[int, int] = {}

        self._lfos: list[LfoClip] = []
        self._lfo_starts: dict[int, int] = {}
        self._lfo_last_sent: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Clip management — call from any thread
    # ------------------------------------------------------------------

    def add(self, clip: Clip) -> None:
        with self._lock:
            self._clips.append(clip)

    def remove(self, clip: Clip) -> None:
        with self._lock:
            self._clips = [c for c in self._clips if c is not clip]
            self._active_starts.pop(id(clip), None)
            self._last_sent.pop(id(clip), None)

    def remove_by_track(self, track: int) -> None:
        with self._lock:
            gone = [c for c in self._clips if c.track == track]
            self._clips = [c for c in self._clips if c.track != track]
            for c in gone:
                self._active_starts.pop(id(c), None)
                self._last_sent.pop(id(c), None)

    def clear(self) -> None:
        with self._lock:
            self._clips.clear()
            self._active_starts.clear()
            self._last_sent.clear()

    @property
    def clips(self) -> list[Clip]:
        with self._lock:
            return list(self._clips)

    def add_lfo(self, lfo: LfoClip) -> None:
        with self._lock:
            self._lfos.append(lfo)

    def remove_lfo(self, lfo: LfoClip) -> None:
        with self._lock:
            self._lfos = [l for l in self._lfos if l is not lfo]
            self._lfo_starts.pop(id(lfo), None)
            self._lfo_last_sent.pop(id(lfo), None)

    def remove_lfos_by_track(self, track: int) -> None:
        with self._lock:
            gone = [l for l in self._lfos if l.track == track]
            self._lfos = [l for l in self._lfos if l.track != track]
            for l in gone:
                self._lfo_starts.pop(id(l), None)
                self._lfo_last_sent.pop(id(l), None)

    def clear_lfos(self) -> None:
        with self._lock:
            self._lfos.clear()
            self._lfo_starts.clear()
            self._lfo_last_sent.clear()

    @property
    def lfos(self) -> list[LfoClip]:
        with self._lock:
            return list(self._lfos)

    # ------------------------------------------------------------------
    # Clock integration — called from the clock daemon thread on every tick
    # ------------------------------------------------------------------

    def on_tick(self, tick_count: int, beat_count: int) -> None:
        with self._lock:
            clips = list(self._clips)
            lfos = list(self._lfos)

        finished: list[Clip] = []
        for clip in clips:
            done = self._evaluate(clip, tick_count, beat_count)
            if done:
                finished.append(clip)

        for lfo in lfos:
            self._evaluate_lfo(lfo, tick_count)

        if finished:
            with self._lock:
                for clip in finished:
                    self._clips = [c for c in self._clips if c is not clip]
                    self._active_starts.pop(id(clip), None)
                    self._last_sent.pop(id(clip), None)

    def _evaluate(self, clip: Clip, tick_count: int, beat_count: int) -> bool:
        """Evaluate one clip. Returns True if the clip is finished and should be removed."""
        if beat_count < clip.start_beat:
            return False  # not started yet

        clip_id = id(clip)
        duration_ticks = clip.duration_beats * PPQN

        with self._lock:
            if clip_id not in self._active_starts:
                self._active_starts[clip_id] = tick_count
            start_tick = self._active_starts[clip_id]

        elapsed = tick_count - start_tick

        if clip.loop:
            elapsed = elapsed % duration_ticks

        if elapsed >= duration_ticks:
            # Send the final value once, then mark as done
            self._send_if_changed(clip, clip.end_value)
            return not clip.loop  # looping clips are never "done"

        t = elapsed / duration_ticks
        self._send_if_changed(clip, clip.value_at(t))
        return False

    def _send_if_changed(self, clip: Clip, value: int) -> None:
        clip_id = id(clip)
        with self._lock:
            if self._last_sent.get(clip_id) == value:
                return
            self._last_sent[clip_id] = value

        if clip.parameter is Parameter.VOLUME:
            self._ctrl.set_volume(clip.track, value)
        elif clip.parameter is Parameter.PAN:
            self._ctrl.set_pan(clip.track, value)
        elif clip.parameter is Parameter.MUTE:
            if value >= 64:
                self._ctrl.mute(clip.track)
            else:
                self._ctrl.unmute(clip.track)

        if self._update_cb:
            self._update_cb(clip.track, clip.parameter, value)

    def _evaluate_lfo(self, lfo: LfoClip, tick_count: int) -> None:
        lfo_id = id(lfo)
        cycle_ticks = lfo.rate_beats * PPQN
        with self._lock:
            if lfo_id not in self._lfo_starts:
                self._lfo_starts[lfo_id] = tick_count
            start_tick = self._lfo_starts[lfo_id]

        elapsed = tick_count - start_tick
        phase = (elapsed % cycle_ticks) / cycle_ticks
        value = lfo.value_at(phase)
        self._send_lfo_if_changed(lfo, value)

    def _send_lfo_if_changed(self, lfo: LfoClip, value: int) -> None:
        lfo_id = id(lfo)
        with self._lock:
            if self._lfo_last_sent.get(lfo_id) == value:
                return
            self._lfo_last_sent[lfo_id] = value

        if lfo.parameter is Parameter.VOLUME:
            self._ctrl.set_volume(lfo.track, value)
        elif lfo.parameter is Parameter.PAN:
            self._ctrl.set_pan(lfo.track, value)
        elif lfo.parameter is Parameter.MUTE:
            if value >= 64:
                self._ctrl.mute(lfo.track)
            else:
                self._ctrl.unmute(lfo.track)

        if self._update_cb:
            self._update_cb(lfo.track, lfo.parameter, value)
