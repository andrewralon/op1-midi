"""
Entry point for the OP-1 MIDI Controller desktop app.

Run with:
    python -m src.app
    python -m src.app -debug
"""

import logging
import signal
import sys

import mido
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.midi_connection import connect
from src.clock import ClockListener, MidiClockGenerator
from src.controller import Controller
from src.automation import AutomationEngine, Parameter
from src.ui import MainWindow, ClockBridge, apply_dark_theme


def main() -> None:
    level = logging.DEBUG if "-debug" in sys.argv else logging.WARNING
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

    try:
        in_port, out_port = connect()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        QMessageBox.critical(None, "MIDI Connection Failed", str(exc))
        sys.exit(1)

    port_name = in_port.name

    controller = Controller(out_port)
    bridge = ClockBridge()

    def on_automation_update(track: int, param: Parameter, value: int) -> None:
        # Runs on the clock daemon thread — only emit signals here.
        bridge.automation_update.emit(track, param.value, value)

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

    # Probe: Universal SysEx Identity Request (F0 7E 7F 06 01 F7)
    # Any response will be captured in the startup log for mode detection research.
    out_port.send(mido.Message("sysex", data=[0x7E, 0x7F, 0x06, 0x01]))

    window = MainWindow(controller, clock, engine, bridge, port_name, clock_gen)
    window.move(0, 0)
    window.show()

    def on_quit() -> None:
        clock_gen.shutdown()
        clock.stop()
        in_port.close()
        out_port.close()

    app.aboutToQuit.connect(on_quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
