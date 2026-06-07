"""
Entry point for the OP-1 MIDI Controller desktop app.

Run with:
    python -m src.app
    venv/bin/python -m src.app
"""

import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from src.midi_connection import connect
from src.clock import ClockListener, MidiClockGenerator
from src.controller import Controller
from src.automation import AutomationEngine, Parameter
from src.ui import MainWindow, ClockBridge, apply_dark_theme


def main() -> None:
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    try:
        in_port, out_port = connect()
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

    clock = ClockListener(
        in_port,
        beat_callback=on_beat,
        tick_callback=engine.on_tick,
        cc_callback=on_cc,
    )
    clock.start()

    clock_gen = MidiClockGenerator(
        out_port,
        tick_callback=engine.on_tick,
        beat_callback=on_beat,
    )

    window = MainWindow(controller, clock, engine, bridge, port_name, clock_gen)
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
