"""
Entry point for the OP-1 MIDI Controller desktop app.

Run with:
    python -m src.app
    python -m src.app --debug
"""

import logging
import signal
import sys

import mido
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.midi_connection import connect, OP1_KEYWORD
from src.clock import ClockListener, MidiClockGenerator
from src.controller import Controller
from src.automation import AutomationEngine, Parameter
from src.ui import MainWindow, ClockBridge, apply_dark_theme


class _NullPort:
    """No-op MIDI port used when running with no device."""
    name = "no device"
    def send(self, msg): pass
    def iter_pending(self): return iter([])
    def close(self): pass


def main() -> None:
    args = sys.argv[1:]
    debug_mode = "--debug" in args
    no_device  = "--no-device" in args

    level = logging.DEBUG if debug_mode else logging.WARNING
    logging.basicConfig(level=level, format="%(message)s")

    app = QApplication(sys.argv)
    apply_dark_theme(app)

    # Qt's C++ event loop blocks Python from handling SIGINT until a Python
    # callback fires. Install a handler that calls app.quit() and use a timer
    # to periodically yield to Python so the signal is caught promptly.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    sigint_timer = QTimer()
    sigint_timer.start(200)
    sigint_timer.timeout.connect(lambda: None)

    # Auto-enable no-device mode when no MIDI ports are available at all.
    if not no_device:
        try:
            if not mido.get_input_names() or not mido.get_output_names():
                no_device = True
        except Exception:
            no_device = True

    if no_device:
        in_port       = _NullPort()
        out_port      = _NullPort()
        in_port_name  = _NullPort.name
        out_port_name = _NullPort.name
    else:
        try:
            raw_in, raw_out = connect()
            in_port       = raw_in  if raw_in  is not None else _NullPort()
            out_port      = raw_out if raw_out is not None else _NullPort()
            in_port_name  = in_port.name
            out_port_name = out_port.name
        except KeyboardInterrupt:
            sys.exit(0)
        except Exception as exc:
            QMessageBox.critical(None, "MIDI Connection Failed", str(exc))
            sys.exit(1)

    controller = Controller(out_port)
    bridge = ClockBridge()

    def on_automation_update(track: int, param: Parameter, value: int | float) -> None:
        # Runs on the clock daemon thread — only emit signals here.
        bridge.automation_update.emit(track, param.value, float(value))

    engine = AutomationEngine(controller, update_callback=on_automation_update)

    def on_beat(beat_num: int) -> None:
        bridge.beat.emit(beat_num)

    def on_cc(channel: int, control: int, value: int) -> None:
        # Runs on the clock daemon thread — emit signal only.
        bridge.cc_received.emit(channel, control, value)

    clock_gen = MidiClockGenerator(
        out_port,
        tick_callback=engine.on_tick,
        beat_callback=on_beat,
    )

    def on_slave_tick(tick_count: int, beat_count: int) -> None:
        # Only drive the engine from the slave clock when the master clock is
        # inactive. If both were active (e.g. OP-1 echoes received ticks back
        # via MIDI thru), the LFO would receive two different tick_counts per
        # period and flicker between two CC values on the device.
        if not clock_gen.clock_enabled:
            engine.on_tick(tick_count, beat_count)

    clock = ClockListener(
        in_port,
        beat_callback=on_beat,
        tick_callback=on_slave_tick,
        cc_callback=on_cc,
    )
    clock.start()

    no_dev = _NullPort.name
    both_no_device = (in_port_name == no_dev and out_port_name == no_dev)

    if not both_no_device:
        # Probe: Universal SysEx Identity Request (F0 7E 7F 06 01 F7)
        # Any response will be captured in the startup log for mode detection research.
        out_port.send(mido.Message("sysex", data=[0x7E, 0x7F, 0x06, 0x01]))

    window = MainWindow(controller, clock, engine, bridge, in_port_name, clock_gen, out_port_name=out_port_name)
    window.move(0, 0)
    window.show()

    if both_no_device:
        def on_quit() -> None:
            clock_gen.shutdown()
            clock.stop()
        app.aboutToQuit.connect(on_quit)
        sys.exit(app.exec())

    # ── Connection polling ──────────────────────────────────────────────────
    # Poll every 500ms. On disconnect: stop threads immediately before they
    # touch the dead port (a segfault in rtmidi, not a Python exception).
    # Do NOT close old ports — Core MIDI cleans them up; closing a dead port
    # is itself what triggers the crash.
    _connected = True

    def _check_connection() -> None:
        nonlocal _connected, in_port, out_port
        try:
            in_names  = mido.get_input_names()
            out_names = mido.get_output_names()
        except Exception:
            # rtmidi raises InvalidPortError when the port list is mid-update
            # (device being removed). Treat as disconnected and retry next tick.
            in_names  = []
            out_names = []
        no_dev = _NullPort.name
        port_present = (in_port_name  == no_dev or in_port_name  in in_names) and \
                       (out_port_name == no_dev or out_port_name in out_names)

        if _connected and not port_present:
            _connected = False
            # Stop threads NOW, before their next read/write on the dead port.
            clock_gen.disable_clock()   # stops sending MIDI clock immediately
            clock.stop()               # stops reading MIDI input
            bridge.disconnected.emit()

        elif not _connected and port_present:
            try:
                new_in  = mido.open_input(in_port_name)
                new_out = mido.open_output(out_port_name)
                controller.set_port(new_out)
                clock_gen.reconnect(new_out)
                clock.reconnect(new_in)
                in_port  = new_in
                out_port = new_out
                _connected = True
                bridge.reconnected.emit()
            except Exception:
                pass  # try again next tick

    conn_timer = QTimer()
    conn_timer.timeout.connect(_check_connection)
    conn_timer.start(500)
    # ───────────────────────────────────────────────────────────────────────

    def on_quit() -> None:
        conn_timer.stop()
        clock_gen.shutdown()
        clock.stop()
        if _connected:
            try:
                in_port.close()
            except Exception:
                pass
            try:
                out_port.close()
            except Exception:
                pass

    app.aboutToQuit.connect(on_quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
