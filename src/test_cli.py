"""
CLI test script — Phase 1 milestone verification.

Behaviour:
  - Connects to the OP-1 Field (auto-detects or prompts).
  - Prints live BPM every 2 seconds.
  - Every 4 beats: toggles mute on track 1 and prints the action.
  - Clean shutdown on Ctrl+C.

Run from the repo root:
    python -m src.test_cli
  or:
    venv/bin/python src/test_cli.py
"""

import sys
import threading
import time

# Allow running as a script from the repo root without installing the package
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.midi_connection import connect
from src.clock import ClockListener
from src.controller import Controller


def main() -> None:
    print("=== OP-1 Field MIDI Test CLI ===\n")

    # --- Connect ---
    in_port, out_port = connect()
    print("\nPorts opened successfully.\n")

    controller = Controller(out_port)

    # --- Beat callback (runs on the clock thread) ---
    # Use a threading.Event so the main loop can react without polling tightly.
    beat_event = threading.Event()
    beat_counter: list[int] = [0]  # mutable container so the closure can write it

    def on_beat(beat_num: int) -> None:
        beat_counter[0] = beat_num
        beat_event.set()

    clock = ClockListener(in_port, beat_callback=on_beat)
    clock.start()
    print("clock listener started. Waiting for MIDI clock from the op1...")
    print("(make sure the op1 is playing or has MIDI sync output enabled.)\n")

    # --- Main loop ---
    last_bpm_print = time.monotonic()
    BPM_INTERVAL = 2.0   # seconds between BPM status prints

    try:
        while True:
            now = time.monotonic()

            # Print BPM every 2 seconds regardless of beats
            if now - last_bpm_print >= BPM_INTERVAL:
                bpm = clock.bpm
                ticks = clock.tick_count
                if bpm is None:
                    print(f"[{now:.1f}s] Waiting for clock ticks... (received {ticks} so far)")
                else:
                    print(f"[{now:.1f}s] BPM: {bpm:.1f}  (tick #{ticks})")
                last_bpm_print = now

            # React to beats — check with a short timeout so BPM prints still fire
            fired = beat_event.wait(timeout=0.1)
            if fired:
                beat_event.clear()
                beat_num = beat_counter[0]

                # Toggle mute on track 1 every 4 beats
                if beat_num % 4 == 0:
                    now_muted = controller.toggle_mute(1)
                    state = "MUTED" if now_muted else "UNMUTED"
                    print(f"  Beat {beat_num}: track 1 → {state}")

    except KeyboardInterrupt:
        print("\n\nCtrl+C received — shutting down...")

    finally:
        clock.stop()
        in_port.close()
        out_port.close()
        print("ports closed. goodbye.")


if __name__ == "__main__":
    main()
