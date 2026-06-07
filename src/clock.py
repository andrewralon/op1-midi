"""
Listens for MIDI clock ticks from the OP-1 Field and calculates live BPM.

MIDI clock standard: 24 Pulse-Per-Quarter-Note (PPQN).
  - One beat = 24 clock ticks.
  - BPM = 60 / (seconds per beat) = 60 / (24 × average_tick_interval_seconds).

Threading model:
  - A dedicated daemon thread reads the input port in a tight loop.
  - Shared state (tick count, BPM) is protected by a threading.Lock.
  - The caller supplies an optional beat_callback that fires on every beat
    (i.e. every 24th tick).  The callback executes on the clock thread, so
    it must be fast / non-blocking.
  - threading.Event is used to signal shutdown — no time.sleep() anywhere.
"""

import threading
import time
from collections import deque
from typing import Callable

import mido

PPQN = 24               # MIDI spec: 24 ticks per quarter note
SMOOTH_N = 24           # number of tick intervals to average for BPM smoothing
MIN_TICKS_FOR_BPM = 4   # need at least this many intervals before reporting BPM


class ClockListener:
    def __init__(
        self,
        in_port: mido.ports.BaseInput,
        beat_callback: Callable[[int], None] | None = None,
        tick_callback: Callable[[int, int], None] | None = None,
        cc_callback: Callable[[int, int, int], None] | None = None,
    ) -> None:
        """
        Args:
            in_port:        Shared mido input port (already open).
            beat_callback:  Called with beat number (1-based) every 24 ticks.
            tick_callback:  Called with (tick_count, beat_count) on every tick.
            cc_callback:    Called with (channel, control, value) for every CC
                            message received — used to sync UI from OP-1 knobs.
        """
        self._port = in_port
        self._beat_callback = beat_callback
        self._tick_callback = tick_callback
        self._cc_callback = cc_callback

        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        self._tick_count: int = 0          # total ticks received since start
        self._beat_count: int = 0          # total beats (tick_count // PPQN)
        self._bpm: float | None = None     # None until enough ticks accumulated

        # Ring buffer of the last SMOOTH_N tick-to-tick intervals (seconds)
        self._intervals: deque[float] = deque(maxlen=SMOOTH_N)
        self._last_tick_time: float | None = None

        self._thread = threading.Thread(target=self._run, daemon=True, name="ClockListener")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    @property
    def tick_count(self) -> int:
        with self._lock:
            return self._tick_count

    @property
    def beat_count(self) -> int:
        with self._lock:
            return self._beat_count

    @property
    def bpm(self) -> float | None:
        """Current BPM, or None if not enough ticks have been received yet."""
        with self._lock:
            return self._bpm

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        # iter_pending() returns messages already in the buffer without
        # blocking, so we interleave it with stop_event checks.
        while not self._stop_event.is_set():
            for msg in self._port.iter_pending():
                if msg.type == "clock":
                    self._handle_tick()
                elif msg.type == "control_change" and self._cc_callback:
                    self._cc_callback(msg.channel, msg.control, msg.value)
            # Yield the GIL briefly rather than busy-spinning
            # (Event.wait with a short timeout replaces time.sleep)
            self._stop_event.wait(timeout=0.001)

    def _handle_tick(self) -> None:
        now = time.perf_counter()  # high-resolution monotonic timer

        with self._lock:
            self._tick_count += 1

            if self._last_tick_time is not None:
                interval = now - self._last_tick_time
                self._intervals.append(interval)

                if len(self._intervals) >= MIN_TICKS_FOR_BPM:
                    avg_interval = sum(self._intervals) / len(self._intervals)
                    # 24 ticks = 1 beat; avg_interval is seconds per tick
                    self._bpm = 60.0 / (PPQN * avg_interval)

            self._last_tick_time = now

            # Fire beat callback every PPQN ticks
            is_beat = self._tick_count % PPQN == 0
            if is_beat:
                self._beat_count += 1
                beat_num = self._beat_count  # capture before releasing lock
            else:
                beat_num = 0

            # Capture snapshots for callbacks (called outside the lock below)
            tick_snap = self._tick_count
            beat_snap = self._beat_count

        # Call outside the lock so callbacks can safely read .bpm / .tick_count
        if self._tick_callback:
            self._tick_callback(tick_snap, beat_snap)
        if is_beat and self._beat_callback:
            self._beat_callback(beat_num)


class MidiClockGenerator:
    """
    Outputs 24 PPQN MIDI clock, making this app the tempo master.

    Clock ticks are sent continuously so slave devices can lock their tempo
    display.  Call play() / stop() to send MIDI Start / Stop transport messages.
    Callbacks mirror ClockListener's API so the same on_beat / on_tick handlers
    in app.py can be reused without changes.
    """

    def __init__(
        self,
        port: mido.ports.BaseOutput,
        tick_callback: Callable[[int, int], None] | None = None,
        beat_callback: Callable[[int], None] | None = None,
    ) -> None:
        self._port          = port
        self._tick_callback = tick_callback
        self._beat_callback = beat_callback
        self._bpm           = 120.0
        self._lock          = threading.Lock()
        self._running       = True
        self._has_started   = False
        self._playing       = False
        self._spp_pos       = 0    # MIDI beats (1 beat = 6 ticks); tracks resume position
        self._spp_tick_rem  = 0    # ticks accumulated toward next MIDI beat
        self._tick_count    = 0
        self._beat_count    = 0
        self._thread = threading.Thread(target=self._run, daemon=True, name="ClockGenerator")
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def bpm(self) -> float:
        with self._lock:
            return self._bpm

    def set_bpm(self, bpm: float) -> None:
        with self._lock:
            self._bpm = max(20.0, min(300.0, float(bpm)))

    def play(self) -> None:
        """Send Start (0xFA) first time; Continue (0xFB) on subsequent presses."""
        self._playing = True
        if self._has_started:
            self._port.send(mido.Message("continue"))
        else:
            self._port.send(mido.Message("start"))
            self._has_started = True

    def stop(self) -> None:
        """Send MIDI Stop (0xFC) and freeze the SPP position."""
        self._playing = False
        self._port.send(mido.Message("stop"))

    def tape_prev_bar(self) -> None:
        """CC 82 + SPP: jump tape and sequencer position back one bar."""
        self._port.send(mido.Message("control_change", channel=0, control=82, value=127))
        with self._lock:
            self._spp_pos = max(0, self._spp_pos - 16)
            spp = self._spp_pos
        self._port.send(mido.Message("songpos", pos=spp))

    def tape_next_bar(self) -> None:
        """CC 83 + SPP: jump tape and sequencer position forward one bar."""
        self._port.send(mido.Message("control_change", channel=0, control=83, value=127))
        with self._lock:
            self._spp_pos += 16
            spp = self._spp_pos
        self._port.send(mido.Message("songpos", pos=spp))

    def shutdown(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        last_tick = time.perf_counter()
        while self._running:
            with self._lock:
                bpm = self._bpm
            tick_interval = 60.0 / (bpm * 24.0)
            next_tick = last_tick + tick_interval
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            self._port.send(mido.Message("clock"))
            self._tick_count += 1
            if self._playing:
                self._spp_tick_rem += 1
                if self._spp_tick_rem >= 6:
                    self._spp_tick_rem = 0
                    self._spp_pos += 1
            is_beat = self._tick_count % PPQN == 0
            if is_beat:
                self._beat_count += 1
            if self._tick_callback:
                self._tick_callback(self._tick_count, self._beat_count)
            if is_beat and self._beat_callback:
                self._beat_callback(self._beat_count)
            last_tick = next_tick
