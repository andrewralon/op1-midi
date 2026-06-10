"""
Listens for MIDI clock ticks from the OP-1 Field and calculates live BPM.

MIDI clock standard: 24 Pulse-Per-Quarter-Note (PPQN).
  - One beat = 24 clock ticks.
  - BPM = 60 / (seconds per beat) = 60 / (24 x average_tick_interval_seconds).

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
        startup_log_seconds: float = 5.0,
    ) -> None:
        """
        Args:
            in_port:               Shared mido input port (already open).
            beat_callback:         Called with beat number (1-based) every 24 ticks.
            tick_callback:         Called with (tick_count, beat_count) on every tick.
            cc_callback:           Called with (channel, control, value) for every CC
                                   message received — used to sync UI from OP-1 knobs.
            startup_log_seconds:   Capture all raw MIDI messages for this many seconds
                                   after start() to help identify per-mode signatures.
                                   Set to 0 to disable.
        """
        self._port = in_port
        self._beat_callback = beat_callback
        self._tick_callback = tick_callback
        self._cc_callback = cc_callback
        self._startup_log_seconds = startup_log_seconds

        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        self._tick_count: int = 0          # total ticks received since start
        self._beat_count: int = 0          # total beats (tick_count // PPQN)
        self._bpm: float | None = None     # None until enough ticks accumulated

        # Ring buffer of the last SMOOTH_N tick-to-tick intervals (seconds)
        self._intervals: deque[float] = deque(maxlen=SMOOTH_N)
        self._last_tick_time: float | None = None

        # Startup message log: records (elapsed_s, msg_repr) for all raw messages
        # received during the first startup_log_seconds after start().
        self._startup_log: list[tuple[float, str]] = []
        self._startup_begin: float | None = None

        self._thread = threading.Thread(target=self._run, daemon=True, name="ClockListener")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._startup_begin = time.perf_counter()
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def reconnect(self, new_port: mido.ports.BaseInput) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        self._port = new_port
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ClockListener")
        self._thread.start()

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

    @property
    def last_tick_time(self) -> float | None:
        """Timestamp (time.perf_counter) of the most recent clock tick, or None."""
        with self._lock:
            return self._last_tick_time

    @property
    def startup_messages(self) -> list[tuple[float, str]]:
        """Copy of (elapsed_s, msg_repr) pairs logged during the startup window."""
        with self._lock:
            return list(self._startup_log)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        # iter_pending() returns messages already in the buffer without
        # blocking, so we interleave it with stop_event checks.
        while not self._stop_event.is_set():
            for msg in self._port.iter_pending():
                self._log_startup_message(msg)
                if msg.type == "clock":
                    self._handle_tick()
                elif msg.type == "start":
                    self._handle_start()
                elif msg.type == "songpos":
                    self._handle_songpos(msg.pos)
                elif msg.type == "control_change" and self._cc_callback:
                    self._cc_callback(msg.channel, msg.control, msg.value)
            # Yield the GIL briefly rather than busy-spinning
            # (Event.wait with a short timeout replaces time.sleep)
            self._stop_event.wait(timeout=0.001)

    def _log_startup_message(self, msg: object) -> None:
        if not self._startup_log_seconds or self._startup_begin is None:
            return
        elapsed = time.perf_counter() - self._startup_begin
        if elapsed > self._startup_log_seconds:
            return
        with self._lock:
            self._startup_log.append((elapsed, repr(msg)))

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

    def _handle_start(self) -> None:
        """OP-1 tape rewound and started — reset position to song beginning."""
        with self._lock:
            self._tick_count = 0
            self._beat_count = 0

    def _handle_songpos(self, pos: int) -> None:
        """Jump to a specific tape position (MIDI SPP: 1 unit = 6 ticks at 24 PPQN)."""
        with self._lock:
            self._tick_count = pos * 6
            self._beat_count = self._tick_count // PPQN


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
        self._bpm           = 100.0
        self._lock          = threading.Lock()
        self._running       = True
        self._clock_enabled = False  # start silent; enabled once MIDI Sync mode is confirmed
        self._has_started   = False
        self._playing       = False
        self._spp_pos       = 0    # MIDI beats (1 beat = 6 ticks); tracks resume position
        self._spp_tick_rem  = 0    # ticks accumulated toward next MIDI beat
        self._tick_count    = 0
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

    def enable_clock(self) -> None:
        self._clock_enabled = True

    def disable_clock(self) -> None:
        self._clock_enabled = False

    @property
    def clock_enabled(self) -> bool:
        return self._clock_enabled

    def play(self) -> None:
        """Send Start (0xFA) first time; Continue (0xFB) on subsequent presses."""
        self._playing = True
        if self._has_started:
            self._safe_send(mido.Message("continue"))
        else:
            self._spp_pos = 0
            self._spp_tick_rem = 0
            self._safe_send(mido.Message("start"))
            self._has_started = True

    def stop(self) -> None:
        """Send MIDI Stop (0xFC) and freeze the SPP position."""
        self._playing = False
        self._safe_send(mido.Message("stop"))

    @property
    def is_playing(self) -> bool:
        return self._playing

    def goto_start(self) -> None:
        """Send SPP 0 to jump the tape to the beginning."""
        self._spp_pos = 0
        self._spp_tick_rem = 0
        self._has_started = False
        self._safe_send(mido.Message("songpos", pos=0))

    def tape_prev_bar(self) -> None:
        """CC 82 + SPP: jump tape and sequencer position back one bar."""
        self._safe_send(mido.Message("control_change", channel=0, control=82, value=127))
        self._spp_pos = max(0, self._spp_pos - 16)
        self._safe_send(mido.Message("songpos", pos=self._spp_pos))
        if self._playing:
            self._safe_send(mido.Message("continue"))

    def tape_next_bar(self) -> None:
        """CC 83 + SPP: jump tape and sequencer position forward one bar."""
        self._safe_send(mido.Message("control_change", channel=0, control=83, value=127))
        self._spp_pos += 16
        self._safe_send(mido.Message("songpos", pos=self._spp_pos))
        if self._playing:
            self._safe_send(mido.Message("continue"))

    def shutdown(self) -> None:
        self._running = False

    def reconnect(self, new_port: mido.ports.BaseOutput) -> None:
        self._running = False
        self._thread.join(timeout=2.0)
        self._port = new_port
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="ClockGenerator")
        self._thread.start()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _safe_send(self, msg: mido.Message) -> None:
        try:
            self._port.send(msg)
        except Exception:
            pass

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
            if self._clock_enabled:
                self._safe_send(mido.Message("clock"))
                self._tick_count += 1
                if self._playing:
                    self._spp_tick_rem += 1
                    if self._spp_tick_rem >= 6:
                        self._spp_tick_rem = 0
                        self._spp_pos += 1
                song_tick = self._spp_pos * 6 + self._spp_tick_rem
                is_beat = self._tick_count % PPQN == 0
                if self._tick_callback:
                    self._tick_callback(self._tick_count, self._tick_count // PPQN)
                if is_beat and self._beat_callback:
                    self._beat_callback(self._tick_count // PPQN)
            last_tick = next_tick
