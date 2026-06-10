"""
Sends MIDI CC messages to the OP-1 Field to control volume, pan, and mute.

CC assignments (MIDI spec / OP-1 convention):
  CC 7  — Channel Volume  (0-127)
  CC 9  — Mute toggle     (≥64 = muted; we use 127=mute, 0=unmute)
  CC 10 — Pan             (0-127; 64 = center)

Tracks 1-4 map to MIDI channels 1-4 (mido uses 0-indexed channels internally).
"""

import threading
import mido

CC_VOLUME = 7
CC_MUTE = 9
CC_PAN = 10
CC_OCTAVE = 79

PAN_CENTER = 64
MUTE_ON = 127
MUTE_OFF = 0

VALID_TRACKS = (1, 2, 3, 4)


class Controller:
    def __init__(self, out_port: mido.ports.BaseOutput) -> None:
        self._port = out_port
        self._lock = threading.Lock()
        # Internal mute state for each track (False = unmuted)
        self._muted: dict[int, bool] = {t: False for t in VALID_TRACKS}

    def set_port(self, new_port: mido.ports.BaseOutput) -> None:
        with self._lock:
            self._port = new_port

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_volume(self, track: int, value: int) -> None:
        """Set channel volume. track 1-4, value 0-127."""
        self._validate_track(track)
        self._validate_value(value, "volume")
        self._send_cc(track, CC_VOLUME, value)

    def set_pan(self, track: int, value: int) -> None:
        """Set pan position. track 1-4, value 0-127 (64 = center)."""
        self._validate_track(track)
        self._validate_value(value, "pan")
        self._send_cc(track, CC_PAN, value)

    def mute(self, track: int) -> None:
        """Mute a track. Idempotent — safe to call if already muted."""
        self._validate_track(track)
        with self._lock:
            self._muted[track] = True
        self._send_cc(track, CC_MUTE, MUTE_ON)

    def unmute(self, track: int) -> None:
        """Unmute a track. Idempotent — safe to call if already unmuted."""
        self._validate_track(track)
        with self._lock:
            self._muted[track] = False
        self._send_cc(track, CC_MUTE, MUTE_OFF)

    def toggle_mute(self, track: int) -> bool:
        """Toggle mute state. Returns True if the track is now muted."""
        self._validate_track(track)
        with self._lock:
            currently_muted = self._muted[track]
            self._muted[track] = not currently_muted
            now_muted = self._muted[track]

        value = MUTE_ON if now_muted else MUTE_OFF
        self._send_cc(track, CC_MUTE, value)
        return now_muted

    def is_muted(self, track: int) -> bool:
        self._validate_track(track)
        with self._lock:
            return self._muted[track]

    def play(self) -> None:
        """Send MIDI Start (0xFA) to the OP-1."""
        self._safe_send(mido.Message("start"))

    def stop(self) -> None:
        """Send MIDI Stop (0xFC) to the OP-1."""
        self._safe_send(mido.Message("stop"))

    def octave_up(self) -> None:
        """Shift octave up via CC 79 ≥ 64 on channel 1."""
        self._safe_send(mido.Message("control_change", channel=0, control=CC_OCTAVE, value=127))

    def octave_down(self) -> None:
        """Shift octave down via CC 79 < 64 on channel 1."""
        self._safe_send(mido.Message("control_change", channel=0, control=CC_OCTAVE, value=0))

    def sync_mute_state(self, track: int, muted: bool) -> None:
        """Update internal mute tracking without sending CC — used to sync from OP-1."""
        self._validate_track(track)
        with self._lock:
            self._muted[track] = muted

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send_cc(self, track: int, cc: int, value: int) -> None:
        # mido channels are 0-indexed; track 1 → channel 0
        self._safe_send(mido.Message("control_change", channel=track - 1, control=cc, value=value))

    def _safe_send(self, msg: mido.Message) -> None:
        try:
            with self._lock:
                self._port.send(msg)
        except Exception:
            pass

    @staticmethod
    def _validate_track(track: int) -> None:
        if track not in VALID_TRACKS:
            raise ValueError(f"track must be 1-4, got {track}")

    @staticmethod
    def _validate_value(value: int, name: str) -> None:
        if not (0 <= value <= 127):
            raise ValueError(f"{name} value must be 0-127, got {value}")
